import json
from datetime import date
from types import SimpleNamespace

import httpx2
import openai as sdk
import pytest

from lavalier.insights.prompt import SYSTEM_PROMPT, DayText, ask_messages, summarize_messages
from lavalier.insights.providers.base import ProviderCheck, ProviderError
from lavalier.insights.providers.openai import DEFAULT_MODEL, MODELS, NO_KEY, OpenAI
from lavalier.insights.schema import INSIGHT_SCHEMA

KEY_TEXT = "sk-openai-secret"
_REQ = httpx2.Request("POST", "https://api.openai.com/v1/responses")


def dt(text="[10:00:00] hello"):
    return DayText(date(2026, 10, 23), text, len(text), False, 0, True)


def api_error(cls, status, message="boom"):
    """The SDK's real exception classes, built with a minimal httpx2 response."""
    return cls(message, response=httpx2.Response(status, request=_REQ), body=None)


class FakeOpenAIClient:
    def __init__(self, reply=None, retrieve_error=None, list_ids=None, list_error=None):
        self.reply, self.retrieve_error, self.list_ids, self.list_error = reply, retrieve_error, list_ids, list_error
        self.calls, self.retrieved = [], []
        self.responses = SimpleNamespace(create=self._create)
        self.models = SimpleNamespace(retrieve=self._retrieve, list=self._list)

    def _create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return SimpleNamespace(output_text=self.reply)

    def _retrieve(self, model_id):
        self.retrieved.append(model_id)
        if self.retrieve_error:
            raise self.retrieve_error
        return SimpleNamespace(id=model_id)

    def _list(self):
        if self.list_error:
            raise self.list_error
        return [SimpleNamespace(id=i) for i in self.list_ids or []]


def adapter(client, model=DEFAULT_MODEL, **kw):
    return OpenAI(model, KEY_TEXT, client=client, **kw)


def test_the_catalogue_and_default():
    assert DEFAULT_MODEL == "gpt-6.1-sol"
    assert [(m.id, m.label, m.recommended, m.cost_per_day) for m in MODELS] == [
        ("gpt-6.1-sol", "GPT-6.1 Sol", True, "about $0.095 per 3-hour day"),
        ("gpt-6-astra", "GPT-6 Astra", False, "about $0.48 per 3-hour day"),
        ("gpt-6-luna", "GPT-6 Luna", False, "about $0.0048 per 3-hour day"),
    ]


def test_summarize_asks_for_a_strict_json_schema():
    c = FakeOpenAIClient(json.dumps({"summary": "A day."}))
    assert adapter(c).summarize(dt()) == {"summary": "A day."}
    assert c.calls == [{
        "model": DEFAULT_MODEL, "instructions": SYSTEM_PROMPT, "input": summarize_messages(dt())[0]["content"],
        "text": {"format": {"type": "json_schema", "name": "insight", "schema": INSIGHT_SCHEMA, "strict": True}},
    }]


@pytest.mark.parametrize("reply", ["not json", "", "[1, 2]", None])
def test_a_reply_that_is_not_a_json_object_is_a_provider_error(reply):
    with pytest.raises(ProviderError, match="did not reply with JSON"):
        adapter(FakeOpenAIClient(reply)).summarize(dt())


def test_ask_returns_the_text_without_a_format():
    c = FakeOpenAIClient("Sam called.")
    assert adapter(c).ask(dt(), "Who called?") == "Sam called."
    assert c.calls == [{"model": DEFAULT_MODEL, "instructions": SYSTEM_PROMPT,
                        "input": ask_messages(dt(), "Who called?")[0]["content"]}]


@pytest.mark.parametrize("reply", ["", "  \n", None])
def test_an_empty_ask_answer_is_a_provider_error(reply):
    with pytest.raises(ProviderError) as e:
        adapter(FakeOpenAIClient(reply)).ask(dt(), "q")
    assert str(e.value) == "The model gave no answer"


@pytest.mark.parametrize("err,text", [
    (api_error(sdk.AuthenticationError, 401, KEY_TEXT), "The key was refused"),
    (api_error(sdk.RateLimitError, 429, KEY_TEXT), "OpenAI is rate-limiting; try again in a minute"),
    (api_error(sdk.InternalServerError, 503, KEY_TEXT), "OpenAI is unavailable; try again later"),
    (sdk.APITimeoutError(request=_REQ), "OpenAI took too long to answer"),
    (api_error(sdk.BadRequestError, 400, "bad input"), "bad input"),
    (sdk.APIConnectionError(request=_REQ), "Could not reach OpenAI"),
    (RuntimeError(KEY_TEXT), "Could not reach OpenAI: RuntimeError"),
])
def test_sdk_errors_become_safe_provider_errors(err, text):
    for call in (lambda a: a.summarize(dt("SECRET DAY TEXT")), lambda a: a.ask(dt("SECRET DAY TEXT"), "q")):
        with pytest.raises(ProviderError) as e:
            call(adapter(FakeOpenAIClient(err)))
        assert str(e.value) == text and "SECRET DAY TEXT" not in str(e.value)


def test_without_a_key_summarize_and_ask_say_so():
    a = OpenAI(DEFAULT_MODEL, None)
    for call in (lambda: a.summarize(dt()), lambda: a.ask(dt(), "q")):
        with pytest.raises(ProviderError, match="^No key saved. Add one in Settings › Model.$"):
            call()


def test_check_without_a_key_names_it():
    assert OpenAI(DEFAULT_MODEL, None).check() == ProviderCheck(False, NO_KEY, MODELS)
    assert NO_KEY == "No key saved. Add one in Settings › Model."


def test_check_with_a_key_retrieves_the_model():
    client = FakeOpenAIClient()
    c = adapter(client, "gpt-6-luna").check()
    assert client.retrieved == ["gpt-6-luna"]
    assert c == ProviderCheck(True, "OpenAI answered; gpt-6-luna is available", MODELS)


@pytest.mark.parametrize("err,detail", [
    (api_error(sdk.AuthenticationError, 401, KEY_TEXT), "The key was refused"),
    (api_error(sdk.NotFoundError, 404, "model: nope"), "model: nope"),
    (RuntimeError(KEY_TEXT), "Could not reach OpenAI: RuntimeError"),
    (sdk.APIConnectionError(request=_REQ), "Could not reach OpenAI"),
])
def test_check_never_raises_and_never_leaks_the_key(err, detail):
    c = adapter(FakeOpenAIClient(retrieve_error=err)).check()
    assert not c.ok and c.detail == detail and c.models == MODELS and KEY_TEXT not in c.detail


def test_the_real_client_is_built_lazily_with_key_base_url_and_timeout(monkeypatch):
    seen = {}

    class Stub:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(sdk, "OpenAI", Stub)
    OpenAI(DEFAULT_MODEL, "k", timeout_s=30)
    assert seen == {"api_key": "k", "base_url": None, "timeout": 30}
    seen.clear()
    OpenAI(DEFAULT_MODEL, "k", base_url="http://localhost:1234/v1")
    assert seen["base_url"] == "http://localhost:1234/v1"
    seen.clear()
    OpenAI(DEFAULT_MODEL, None)
    assert seen == {}


def test_a_base_url_is_named_in_facts_and_check_lists_the_endpoints_models():
    url = "http://localhost:1234/v1"
    client = FakeOpenAIClient(list_ids=["local-a", "local-b"])
    a = adapter(client, "local-a", base_url=url)
    assert a.facts() == {"sends": "each day's transcript text and your questions, never audio",
                         "to": f"the endpoint at {url}", "cost": "set by that endpoint"}
    c = a.check()
    assert c.ok and c.detail == "OpenAI answered; local-a is available"
    assert [(m.id, m.label, m.cost_per_day) for m in c.models] == [("local-a", "local-a", None),
                                                                   ("local-b", "local-b", None)]


def test_with_a_base_url_check_falls_back_to_the_configured_model_when_listing_fails():
    a = adapter(FakeOpenAIClient(list_error=RuntimeError(KEY_TEXT)), "local-a", base_url="http://x/v1")
    c = a.check()
    assert c.ok and [m.id for m in c.models] == ["local-a"]


def test_facts_without_a_base_url_use_the_models_cost_or_a_fallback():
    f = OpenAI("gpt-6-luna", "k", client=FakeOpenAIClient()).facts()
    assert f == {"sends": "each day's transcript text and your questions, never audio", "to": "OpenAI",
                 "cost": "about $0.0048 per 3-hour day"}
    assert OpenAI("gpt-future", "k", client=FakeOpenAIClient()).facts()["cost"] == "about $0.095 per 3-hour day"
