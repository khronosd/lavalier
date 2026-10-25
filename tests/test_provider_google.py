import json
from datetime import date
from types import SimpleNamespace

import google.genai as sdk
import httpx2
import pytest
from google.genai import errors

from lavalier.insights.prompt import SYSTEM_PROMPT, DayText, ask_messages, summarize_messages
from lavalier.insights.providers.base import ProviderCheck, ProviderError
from lavalier.insights.providers.google import DEFAULT_MODEL, MODELS, NO_KEY, Google
from lavalier.insights.schema import INSIGHT_SCHEMA

KEY_TEXT = "AIza-google-secret"


def dt(text="[10:00:00] hello"):
    return DayText(date(2026, 10, 23), text, len(text), False, 0, True)


def api_error(cls, code, message="boom", status="STATUS"):
    """The SDK's real exception classes, built from the JSON body Google sends."""
    return cls(code, {"error": {"code": code, "message": message, "status": status}})


class FakeGoogleClient:
    def __init__(self, reply=None, get_error=None):
        self.reply, self.get_error, self.calls, self.got = reply, get_error, [], []
        self.models = SimpleNamespace(generate_content=self._generate, get=self._get)

    def _generate(self, **kw):
        self.calls.append(kw)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return SimpleNamespace(text=self.reply)

    def _get(self, *, model):
        self.got.append(model)
        if self.get_error:
            raise self.get_error
        return SimpleNamespace(name=model)


def adapter(client, model=DEFAULT_MODEL):
    return Google(model, KEY_TEXT, client=client)


def test_the_catalogue_and_default():
    assert DEFAULT_MODEL == "gemini-3.8-flash"
    assert [(m.id, m.label, m.recommended, m.cost_per_day) for m in MODELS] == [
        ("gemini-3.8-flash", "Gemini 3.8 Flash", True, "about $0.036 per 3-hour day"),
        ("gemini-4-argon", "Gemini 4 Argon", False, "about $0.095 per 3-hour day"),
        ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", False, "about $0.016 per 3-hour day"),
    ]


def test_summarize_asks_for_json_with_the_schema():
    c = FakeGoogleClient(json.dumps({"summary": "A day."}))
    assert adapter(c).summarize(dt()) == {"summary": "A day."}
    assert c.calls == [{
        "model": DEFAULT_MODEL, "contents": summarize_messages(dt())[0]["content"],
        "config": {"system_instruction": SYSTEM_PROMPT, "response_mime_type": "application/json",
                   "response_json_schema": INSIGHT_SCHEMA, "temperature": 0.2},
    }]


def test_the_config_is_accepted_by_the_installed_sdk():
    from google.genai import types

    a = adapter(FakeGoogleClient("{}"))
    a.summarize(dt())
    types.GenerateContentConfig(**a._client.calls[0]["config"])  # raises on an unknown field


@pytest.mark.parametrize("reply", ["not json", "", "[1, 2]", None])
def test_a_reply_that_is_not_a_json_object_is_a_provider_error(reply):
    with pytest.raises(ProviderError, match="did not reply with JSON"):
        adapter(FakeGoogleClient(reply)).summarize(dt())


def test_ask_returns_the_text_without_a_schema():
    c = FakeGoogleClient("Sam called.")
    assert adapter(c).ask(dt(), "Who called?") == "Sam called."
    assert c.calls == [{"model": DEFAULT_MODEL, "contents": ask_messages(dt(), "Who called?")[0]["content"],
                        "config": {"system_instruction": SYSTEM_PROMPT, "temperature": 0.2}}]


@pytest.mark.parametrize("reply", ["", "  \n", None])
def test_an_empty_ask_answer_is_a_provider_error(reply):
    with pytest.raises(ProviderError) as e:
        adapter(FakeGoogleClient(reply)).ask(dt(), "q")
    assert str(e.value) == "The model gave no answer"


@pytest.mark.parametrize("err,text", [
    (api_error(errors.ClientError, 401, KEY_TEXT), "The key was refused"),
    (api_error(errors.ClientError, 403, KEY_TEXT), "The key was refused"),
    (api_error(errors.ClientError, 400, "API key not valid. Please pass a valid API key."), "The key was refused"),
    (api_error(errors.ClientError, 429, KEY_TEXT), "Google is rate-limiting; try again in a minute"),
    (api_error(errors.ServerError, 503, KEY_TEXT), "Google is unavailable; try again later"),
    (httpx2.ReadTimeout("slow"), "Google took too long to answer"),
    (TimeoutError(KEY_TEXT), "Google took too long to answer"),
    (httpx2.ConnectError(KEY_TEXT), "Could not reach Google"),
    (api_error(errors.ClientError, 400, "bad input"), "bad input"),
    (RuntimeError(KEY_TEXT), "Could not reach Google: RuntimeError"),
])
def test_sdk_errors_become_safe_provider_errors(err, text):
    for call in (lambda a: a.summarize(dt("SECRET DAY TEXT")), lambda a: a.ask(dt("SECRET DAY TEXT"), "q")):
        with pytest.raises(ProviderError) as e:
            call(adapter(FakeGoogleClient(err)))
        assert str(e.value) == text and "SECRET DAY TEXT" not in str(e.value)


def test_without_a_key_summarize_and_ask_say_so():
    a = Google(DEFAULT_MODEL, None)
    for call in (lambda: a.summarize(dt()), lambda: a.ask(dt(), "q")):
        with pytest.raises(ProviderError, match="^No key saved. Add one in Settings › Model.$"):
            call()


def test_check_without_a_key_names_it():
    assert Google(DEFAULT_MODEL, None).check() == ProviderCheck(False, NO_KEY, MODELS)
    assert NO_KEY == "No key saved. Add one in Settings › Model."


def test_check_with_a_key_gets_the_model():
    client = FakeGoogleClient()
    c = adapter(client, "gemini-4-argon").check()
    assert client.got == ["gemini-4-argon"]
    assert c == ProviderCheck(True, "Google answered; gemini-4-argon is available", MODELS)


@pytest.mark.parametrize("err,detail", [
    (api_error(errors.ClientError, 403, KEY_TEXT), "The key was refused"),
    (api_error(errors.ClientError, 404, "model: nope"), "model: nope"),
    (RuntimeError(KEY_TEXT), "Could not reach Google: RuntimeError"),
    (httpx2.ConnectError(KEY_TEXT), "Could not reach Google"),
])
def test_check_never_raises_and_never_leaks_the_key(err, detail):
    c = adapter(FakeGoogleClient(get_error=err)).check()
    assert not c.ok and c.detail == detail and c.models == MODELS and KEY_TEXT not in c.detail


def test_the_real_client_is_built_lazily_with_the_key_and_timeout_in_ms(monkeypatch):
    seen = {}

    class Stub:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(sdk, "Client", Stub)
    Google(DEFAULT_MODEL, "k", timeout_s=30)
    assert seen == {"api_key": "k", "http_options": {"timeout": 30000}}
    seen.clear()
    Google(DEFAULT_MODEL, None)
    assert seen == {}


def test_facts_use_the_models_cost_or_a_fallback():
    f = Google("gemini-3.5-flash-lite", "k", client=FakeGoogleClient()).facts()
    assert f == {"sends": "each day's transcript text and your questions, never audio", "to": "Google",
                 "cost": "about $0.016 per 3-hour day"}
    assert Google("gemini-future", "k", client=FakeGoogleClient()).facts()["cost"] == "about $0.036 per 3-hour day"
