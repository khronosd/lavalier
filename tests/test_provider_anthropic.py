import json
from datetime import date
from types import SimpleNamespace

import anthropic as sdk
import httpx2
import pytest

from lavalier.insights.prompt import SYSTEM_PROMPT, DayText, ask_messages, summarize_messages
from lavalier.insights.providers.anthropic import DEFAULT_MODEL, MODELS, Anthropic
from lavalier.insights.providers.base import ProviderCheck, ProviderError
from lavalier.insights.schema import INSIGHT_SCHEMA

KEY_TEXT = "sk-ant-secret"
_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def dt(text="[10:00:00] hello"):
    return DayText(date(2026, 10, 23), text, len(text), False, 0, True)


def api_error(cls, status, message="boom"):
    """The SDK's real exception classes, built with a minimal httpx2 response."""
    return cls(message, response=httpx2.Response(status, request=_REQ), body=None)


def msg(text="", stop_reason="end_turn", blocks=None):
    content = blocks if blocks is not None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class _Stream:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        if isinstance(self.owner.reply, BaseException):
            raise self.owner.reply
        return self.owner.reply


class FakeAnthropicClient:
    def __init__(self, reply=None, retrieve_error=None):
        self.reply, self.retrieve_error, self.calls, self.retrieved = reply, retrieve_error, [], []
        self.messages = SimpleNamespace(stream=self._stream)
        self.models = SimpleNamespace(retrieve=self._retrieve)

    def _stream(self, **kw):
        self.calls.append(kw)
        return _Stream(self)

    def _retrieve(self, model_id):
        self.retrieved.append(model_id)
        if self.retrieve_error:
            raise self.retrieve_error
        return SimpleNamespace(id=model_id)


def adapter(client, model=DEFAULT_MODEL):
    return Anthropic(model, KEY_TEXT, client=client)


def test_the_catalogue_and_default():
    assert DEFAULT_MODEL == "claude-opus-5-5"
    assert [m.id for m in MODELS] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    assert [m.recommended for m in MODELS] == [True, False, False]


def test_summarize_streams_with_the_schema_and_medium_effort():
    c = FakeAnthropicClient(msg(json.dumps({"summary": "A day."})))
    out = adapter(c).summarize(dt())
    kw = c.calls[0]
    assert out == {"summary": "A day."}
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": INSIGHT_SCHEMA}, "effort": "medium"}
    assert "thinking" not in kw and kw["max_tokens"] == 4096
    assert kw["model"] == DEFAULT_MODEL and kw["system"] == SYSTEM_PROMPT
    assert kw["messages"] == summarize_messages(dt())


def test_summarize_skips_non_text_blocks():
    blocks = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text='{"summary": "x"}')]
    assert adapter(FakeAnthropicClient(msg(blocks=blocks))).summarize(dt()) == {"summary": "x"}


def test_a_refusal_is_a_provider_error():
    with pytest.raises(ProviderError) as e:
        adapter(FakeAnthropicClient(msg("", "refusal", blocks=[]))).summarize(dt())
    assert str(e.value) == "The model declined to summarise this day"


def test_a_cut_off_reply_is_a_provider_error():
    with pytest.raises(ProviderError) as e:
        adapter(FakeAnthropicClient(msg('{"summ', "max_tokens"))).summarize(dt())
    assert str(e.value) == "The reply was cut off"


@pytest.mark.parametrize("reply", [msg("not json"), msg(blocks=[]), msg("[1, 2]")])
def test_a_reply_that_is_not_a_json_object_is_a_provider_error(reply):
    with pytest.raises(ProviderError, match="did not reply with JSON"):
        adapter(FakeAnthropicClient(reply)).summarize(dt())


def test_ask_returns_the_text_without_a_format():
    blocks = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="Sam "),
              SimpleNamespace(type="text", text="called.")]
    c = FakeAnthropicClient(msg(blocks=blocks))
    assert adapter(c).ask(dt(), "Who called?") == "Sam called."
    kw = c.calls[0]
    assert kw["output_config"] == {"effort": "medium"} and "thinking" not in kw and kw["max_tokens"] == 2048
    assert kw["messages"] == ask_messages(dt(), "Who called?") and kw["system"] == SYSTEM_PROMPT


def test_ask_refusal_and_cut_off():
    with pytest.raises(ProviderError, match="declined"):
        adapter(FakeAnthropicClient(msg("", "refusal"))).ask(dt(), "q")
    with pytest.raises(ProviderError, match="cut off"):
        adapter(FakeAnthropicClient(msg("partial", "max_tokens"))).ask(dt(), "q")


@pytest.mark.parametrize("err,text", [
    (api_error(sdk.AuthenticationError, 401, KEY_TEXT), "The key was refused"),
    (api_error(sdk.RateLimitError, 429, KEY_TEXT), "Anthropic is rate-limiting; try again in a minute"),
    (api_error(sdk.InternalServerError, 529, KEY_TEXT), "Anthropic is overloaded; try again later"),
    (sdk.APITimeoutError(request=_REQ), "Anthropic took too long to answer"),
    (api_error(sdk.BadRequestError, 400, "bad input"), "bad input"),
    (sdk.APIConnectionError(request=_REQ), "Could not reach Anthropic: APIConnectionError"),
    (RuntimeError(KEY_TEXT), "Could not reach Anthropic: RuntimeError"),
])
def test_sdk_errors_become_safe_provider_errors(err, text):
    for call in (lambda a: a.summarize(dt("SECRET DAY TEXT")), lambda a: a.ask(dt("SECRET DAY TEXT"), "q")):
        with pytest.raises(ProviderError) as e:
            call(adapter(FakeAnthropicClient(err)))
        assert str(e.value) == text and "SECRET DAY TEXT" not in str(e.value)


def test_without_a_key_summarize_and_ask_say_so():
    a = Anthropic(DEFAULT_MODEL, None)
    for call in (lambda: a.summarize(dt()), lambda: a.ask(dt(), "q")):
        with pytest.raises(ProviderError, match="^No key saved. Add one in Settings › Model.$"):
            call()


def test_check_without_a_key_names_it():
    c = Anthropic("claude-opus-5-5", None).check()
    assert c == ProviderCheck(False, "No key saved. Add one in Settings › Model.", MODELS) and c.detail.startswith("No key saved")


def test_check_with_a_key_retrieves_the_model():
    client = FakeAnthropicClient()
    c = adapter(client, "claude-sonnet-5-5").check()
    assert client.retrieved == ["claude-sonnet-5-5"]
    assert c.ok and c.detail == "Anthropic answered; claude-sonnet-5-5 is available" and c.models == MODELS


@pytest.mark.parametrize("err,detail", [
    (api_error(sdk.AuthenticationError, 401, KEY_TEXT), "The key was refused"),
    (api_error(sdk.NotFoundError, 404, "model: nope"), "model: nope"),
    (RuntimeError(KEY_TEXT), "Could not reach Anthropic: RuntimeError"),
    (sdk.APIConnectionError(request=_REQ), "Could not reach Anthropic: APIConnectionError"),
])
def test_check_never_raises_and_never_leaks_the_key(err, detail):
    c = adapter(FakeAnthropicClient(retrieve_error=err)).check()
    assert not c.ok and c.detail == detail and c.models == MODELS and KEY_TEXT not in c.detail


def test_the_real_client_is_built_lazily_with_the_key_and_timeout(monkeypatch):
    seen = {}

    class Stub:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(sdk, "Anthropic", Stub)
    Anthropic(DEFAULT_MODEL, "k", timeout_s=30)
    assert seen == {"api_key": "k", "timeout": 30, "max_retries": 2}
    seen.clear()
    Anthropic(DEFAULT_MODEL, None)
    assert seen == {}


def test_facts_use_the_models_cost_or_a_fallback():
    f = Anthropic("claude-haiku-5-5", "k", client=FakeAnthropicClient()).facts()
    assert f == {"sends": "each day's transcript text and your questions, never audio", "to": "Anthropic",
                 "cost": "about $0.005 per 3-hour day"}
    assert Anthropic("claude-future-9", "k", client=FakeAnthropicClient()).facts()["cost"] == "about $0.20 per 3-hour day"


def test_the_catalogue_pins_labels_and_costs():
    assert [(m.label, m.cost_per_day) for m in MODELS] == [
        ("Claude Opus 5.5", "about $0.20 per 3-hour day"),
        ("Claude Sonnet 5.5", "about $0.10 per 3-hour day"),
        ("Claude Haiku 5.5", "about $0.005 per 3-hour day"),
    ]


@pytest.mark.parametrize("reply", [msg(""), msg(blocks=[]), msg("  \n")])
def test_an_empty_ask_answer_is_a_provider_error(reply):
    with pytest.raises(ProviderError) as e:
        adapter(FakeAnthropicClient(reply)).ask(dt(), "q")
    assert str(e.value) == "The model gave no answer"
