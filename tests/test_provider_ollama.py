import http.client
import io
import json
import socket
import urllib.error
from datetime import date

import pytest
from fake_ollama import FakeOllama

from lavalier.insights.prompt import SYSTEM_PROMPT, DayText, ask_messages, summarize_messages
from lavalier.insights.providers.base import ModelInfo, ProviderCheck, ProviderError
from lavalier.insights.providers.ollama import NOT_RUNNING, SIZE_CLASSES, Ollama, num_ctx, recommended_model
from lavalier.insights.schema import INSIGHT_SCHEMA


def dt(text="[10:00:00] hello", chars=None):
    return DayText(date(2026, 10, 23), text, len(text) if chars is None else chars, False, 0, True)


@pytest.fixture
def fake():
    with FakeOllama(models=["m", "other"], chat_content=json.dumps({"summary": "A day."})) as f:
        yield f


@pytest.fixture
def fake_500():
    with FakeOllama(fail_status=500) as f:
        yield f


def test_summarize_posts_the_schema_and_returns_the_object(fake):
    out = Ollama("m", url=fake.url, memory_gb=16).summarize(dt())
    method, path, req = fake.requests[0]
    assert (method, path) == ("POST", "/api/chat")
    assert req["format"] == INSIGHT_SCHEMA and req["stream"] is False and req["model"] == "m"
    assert req["messages"] == [{"role": "system", "content": SYSTEM_PROMPT}, *summarize_messages(dt())]
    assert req["options"] == {"num_ctx": 8192, "temperature": 0.2}
    assert out["summary"] == "A day."
    assert fake.headers[0]["Content-Type"] == "application/json"


def test_ask_posts_without_a_format_and_returns_the_text():
    with FakeOllama(chat_content="Sam called.") as f:
        out = Ollama("m", url=f.url).ask(dt(), "Who called?")
        req = f.requests[0][2]
    assert out == "Sam called." and "format" not in req and req["stream"] is False
    assert req["messages"] == [{"role": "system", "content": SYSTEM_PROMPT}, *ask_messages(dt(), "Who called?")]


def test_summarize_with_non_json_content_is_a_provider_error():
    with FakeOllama(chat_content="not json") as f:
        with pytest.raises(ProviderError, match="did not reply with JSON"):
            Ollama("m", url=f.url).summarize(dt())


def test_ollama_num_ctx_follows_the_text_size():
    assert num_ctx(4_000) == 8192 and num_ctx(40_000) == 16384 and num_ctx(1_000_000) == 32768
    assert num_ctx(0) == 8192 and num_ctx(24_572) == 8192 and num_ctx(24_580) == 16384 and num_ctx(60_000) == 32768


def test_check_lists_models_and_marks_the_recommended_one(fake):
    rec = recommended_model(16)
    fake.models = ["m", rec]
    c = Ollama("m", url=fake.url, memory_gb=16).check()
    assert c.ok and c.detail == "Ollama is running with 2 model(s)"
    assert c.models == [
        ModelInfo("m", "m", False, "free, runs on this Mac"),
        ModelInfo(rec, rec, True, "free, runs on this Mac"),
    ]


def test_check_when_the_model_is_not_pulled(fake):
    c = Ollama("missing", url=fake.url, memory_gb=16).check()
    assert not c.ok and c.detail == "Pull missing in Ollama first" and [m.id for m in c.models] == ["m", "other"]


def test_check_when_ollama_is_down_explains():
    c = Ollama("m", url="http://127.0.0.1:1").check()
    assert c == ProviderCheck(False, NOT_RUNNING, [])


def test_check_never_raises_on_garbage():
    def opener(req, timeout=None):
        return io.BytesIO(b"<html>")
    c = Ollama("m", opener=opener).check()
    assert not c.ok and c.models == []


def test_an_http_error_becomes_a_provider_error(fake_500):
    with pytest.raises(ProviderError, match="Ollama answered 500: boom") as e:
        Ollama("m", url=fake_500.url).summarize(dt())
    assert len(str(e.value)) < 260


def test_connection_refused_and_timeout_are_mapped():
    with pytest.raises(ProviderError) as e:
        Ollama("m", url="http://127.0.0.1:1").ask(dt(), "q")
    assert str(e.value) == NOT_RUNNING

    def slow(req, timeout=None):
        raise socket.timeout("timed out")
    with pytest.raises(ProviderError) as e:
        Ollama("m", opener=slow).ask(dt(), "q")
    assert str(e.value) == "Ollama took too long to answer"

    def slow_url(req, timeout=None):
        raise urllib.error.URLError(socket.timeout("timed out"))
    with pytest.raises(ProviderError, match="too long"):
        Ollama("m", opener=slow_url).ask(dt(), "q")


def test_facts_say_nothing_leaves_the_mac():
    f = Ollama("m").facts()
    assert "this Mac" in f["to"] and f["cost"] == "free, runs on this Mac" and set(f) == {"sends", "to", "cost"}


def test_recommended_model_follows_memory():
    assert recommended_model(8) == SIZE_CLASSES[0][1] and recommended_model(16) == SIZE_CLASSES[0][1]
    assert recommended_model(24) == SIZE_CLASSES[1][1] and recommended_model(32) == SIZE_CLASSES[1][1]
    assert recommended_model(64) == SIZE_CLASSES[2][1]


def test_memory_defaults_to_the_machine():
    assert Ollama("m").memory_gb > 0


def test_a_half_dead_server_is_a_provider_error_and_check_does_not_raise():
    def broken(req, timeout=None):
        raise http.client.IncompleteRead(b"")
    p = Ollama("m", opener=broken)
    with pytest.raises(ProviderError, match="broken reply"):
        p.summarize(dt())
    c = p.check()
    assert not c.ok and c.detail == "Ollama sent a broken reply" and c.models == []


def test_check_catches_anything_unexpected():
    def odd(req, timeout=None):
        raise RuntimeError("secret detail")
    c = Ollama("m", opener=odd).check()
    assert c == ProviderCheck(False, "Could not reach Ollama: RuntimeError", [])


def test_other_connection_failures_are_not_reported_as_not_running():
    def dns(req, timeout=None):
        raise urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided"))
    with pytest.raises(ProviderError, match="Could not reach Ollama: .*nodename"):
        Ollama("m", opener=dns).ask(dt(), "q")


def test_a_json_reply_without_a_message_is_a_safe_error():
    def opener(req, timeout=None):
        return io.BytesIO(b'{"done": true}')
    with pytest.raises(ProviderError, match="could not be read"):
        Ollama("m", opener=opener).summarize(dt())


def test_check_uses_a_short_timeout():
    seen = []

    def opener(req, timeout=None):
        seen.append(timeout)
        return io.BytesIO(b'{"models": []}')
    Ollama("m", opener=opener, timeout_s=300).check()
    assert seen == [10]


@pytest.mark.parametrize("content", ["", "  \n"])
def test_an_empty_ask_answer_is_a_provider_error(content):
    with FakeOllama(chat_content=content) as f:
        with pytest.raises(ProviderError) as e:
            Ollama("m", url=f.url).ask(dt(), "q")
    assert str(e.value) == "The model gave no answer"
