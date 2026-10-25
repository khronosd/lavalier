import dataclasses
import json
import logging
import threading
import time
from datetime import date

import pytest

from conftest import BrokenKeyring, _serve_real_app, delete, get, post, put
from fake_pendant import FakePendant
from fake_provider import FakeProvider
from lavalier.insights import keys, registry

DAY = "2026-10-23"


def _body(r):
    return json.loads(r.read())


def _wait_job(server, job_id: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        j = _body(get(server, f"/api/jobs/{job_id}"))
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("the job never finished")


@pytest.fixture
def fake_provider():
    return FakeProvider()


@pytest.fixture
def insights_server(app_env, db, seeded_2026_10_23_subset, fake_provider):
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, insights_provider="ollama")
    app.provider_factory = lambda cfg: fake_provider
    yield from _serve_real_app(app, db)


@pytest.fixture
def server_no_provider(app_env, db, seeded_2026_10_23_subset):
    yield from _serve_real_app(app_env(FakePendant()), db)


def test_generate_without_a_usable_provider_is_400_with_the_reason(server_no_provider):
    r = post(server_no_provider, f"/api/insights/generate/{DAY}")
    assert r.status == 400 and _body(r)["error"] == "No model chosen."
    r = post(server_no_provider, "/api/ask", {"day": DAY, "question": "who?"})
    assert r.status == 400 and _body(r)["error"] == "No model chosen."
    assert _body(get(server_no_provider, f"/api/insights/{DAY}"))["reason"] == "No model chosen."


def test_generate_returns_a_job_and_the_day_reads_generating_then_done(insights_server, fake_provider):
    fake_provider.gate = threading.Event()
    assert _body(get(insights_server, f"/api/insights/{DAY}"))["state"] == "none"
    r = post(insights_server, f"/api/insights/generate/{DAY}")
    assert r.status == 202
    job = _body(r)["job"]
    day = _body(get(insights_server, f"/api/insights/{DAY}"))
    assert day["state"] == "generating" and day["job"] == job
    assert _body(get(insights_server, "/api/insights"))["generating"] == [DAY]
    fake_provider.gate.set()
    j = _wait_job(insights_server, job)
    assert j["state"] == "done" and j["result"]["stored"] is True
    day = _body(get(insights_server, f"/api/insights/{DAY}"))
    assert day["state"] == "done" and day["job"] is None and day["reason"] is None
    assert day["record"]["insight"]["summary"].startswith("A short pendant test")


def test_a_second_generate_for_the_same_day_is_409(insights_server, fake_provider):
    fake_provider.gate = threading.Event()
    job = _body(post(insights_server, f"/api/insights/generate/{DAY}"))["job"]
    try:
        assert post(insights_server, f"/api/insights/generate/{DAY}").status == 409
    finally:
        fake_provider.gate.set()
    _wait_job(insights_server, job)


def test_bad_days_bodies_and_jobs(insights_server):
    assert post(insights_server, "/api/insights/generate/2026-13-01").status == 400
    assert get(insights_server, "/api/insights/nope").status == 400
    assert get(insights_server, "/api/jobs/unknown").status == 404
    assert post(insights_server, "/api/ask", {"day": DAY, "question": "  "}).status == 400
    assert post(insights_server, "/api/ask", {"day": DAY}).status == 400
    assert post(insights_server, "/api/ask", b"not json").status == 400
    for days in (0, 366, "3", None):
        assert post(insights_server, "/api/insights/generate-range", {"days": days}).status == 400


def test_ask_returns_a_job_whose_result_is_the_answer(insights_server, fake_provider):
    fake_provider.answer = "You tested the pendant."
    r = post(insights_server, "/api/ask", {"day": DAY, "question": "what happened?"})
    assert r.status == 202
    j = _wait_job(insights_server, _body(r)["job"])
    assert j["state"] == "done" and j["result"] == {"answer": "You tested the pendant."}


def test_generate_range_is_one_job(insights_server, fake_provider):
    r = post(insights_server, "/api/insights/generate-range", {"days": 7})
    assert r.status == 202
    j = _wait_job(insights_server, _body(r)["job"])
    assert j["state"] == "done" and j["kind"] == "generate_range" and j["result"]["errors"] == []


def test_the_index_route(insights_server):
    idx = _body(get(insights_server, "/api/insights"))
    assert {"follow_ups", "people", "topics", "days_without", "generating", "due", "auto"} <= idx.keys()


def test_keys_put_never_echoes_and_get_providers_shows_only_presence(app_env, db, seeded_2026_10_23_subset,
                                                                     memory_keyring, caplog):
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, insights_provider="anthropic")
    caplog.set_level(logging.DEBUG)
    for srv in _serve_real_app(app, db):
        before = _body(get(srv, "/api/insights/providers"))
        assert before["key_present"] is False and before["check"] is None
        r = put(srv, "/api/keys/anthropic", {"key": "sk-secret-1"})
        assert r.status == 204 and r.read() == b""
        assert keys.get_key("anthropic") == "sk-secret-1"
        r = get(srv, "/api/insights/providers")
        assert "sk-secret-1" not in r.read().decode() and _body(r)["key_present"] is True
        assert "sk-secret-1" not in json.dumps(_body(get(srv, "/api/status")))
        assert _body(get(srv, f"/api/insights/{DAY}"))["reason"] is None       # the route noted the key
        assert delete(srv, "/api/keys/anthropic").status == 204 and keys.get_key("anthropic") is None
        assert _body(get(srv, f"/api/insights/{DAY}"))["reason"] == "No key saved. Add one in Settings › Model."
        assert put(srv, "/api/keys/ollama", {"key": "x"}).status == 400
        assert put(srv, "/api/keys/nope", {"key": "x"}).status == 400
        assert put(srv, "/api/keys/anthropic", {"key": 5}).status == 400
        assert delete(srv, "/api/keys/nope").status == 400
        assert put(srv, "/api/keys/anthropic", {"key": "sk-x"}, token=None).status == 401
        assert put(srv, "/api/keys/anthropic", {"key": "sk-x"}, origin="http://evil.test").status == 403
    assert "sk-secret-1" not in caplog.text


def test_a_keychain_refusal_is_503_with_its_message_and_no_key(server_no_provider):
    import keyring
    keyring.set_keyring(BrokenKeyring())
    r = put(server_no_provider, "/api/keys/openai", {"key": "sk-secret-2"})
    text = r.read().decode()
    assert r.status == 503 and "The Keychain refused" in json.loads(text)["error"] and "sk-secret-2" not in text
    assert delete(server_no_provider, "/api/keys/openai").status == 503


def test_check_runs_the_providers_check(insights_server, monkeypatch):
    from lavalier.insights.providers.base import ProviderCheck
    monkeypatch.setattr(registry, "check", lambda cfg: ProviderCheck(True, f"reached {cfg.insights_provider}", []))
    r = post(insights_server, "/api/insights/check")
    assert r.status == 200 and _body(r) == {"ok": True, "detail": "reached ollama", "models": []}


def test_check_is_504_past_its_cap(insights_server, monkeypatch):
    from lavalier import server
    gate = threading.Event()
    monkeypatch.setattr(server, "CHECK_TIMEOUT_S", 0.05)
    monkeypatch.setattr(registry, "check", lambda cfg: gate.wait(5))
    try:
        assert post(insights_server, "/api/insights/check").status == 504
    finally:
        gate.set()


def test_choosing_a_provider_records_when(server_no_provider):
    assert put(server_no_provider, "/api/settings", {"insights_provider": "ollama"}).status == 200
    assert server_no_provider.app.db.get_status("insights_enabled_at_ms")


def test_the_status_carries_the_insights_block(insights_server):
    s = _body(get(insights_server, "/api/status"))["insights"]
    assert s["provider"] == "ollama" and s["generating"] == [] and s["auto"] is True


def test_a_stopping_app_refuses_new_insights_work_with_503(insights_server):
    insights_server.app._app._stopping = True
    assert post(insights_server, f"/api/insights/generate/{DAY}").status == 503
    assert post(insights_server, "/api/ask", {"day": DAY, "question": "who?"}).status == 503


# --- final fix wave

def test_the_key_routes_use_the_current_endpoints_account(app_env, db, seeded_2026_10_23_subset, memory_keyring):
    for srv in _serve_real_app(app_env(FakePendant()), db):
        assert put(srv, "/api/settings", {"insights_provider": "openai"}).status == 200
        assert put(srv, "/api/keys/openai", {"key": "sk-openai"}).status == 204
        assert keys.get_key("openai") == "sk-openai"
        assert put(srv, "/api/settings", {"insights_base_url": "http://llm.example.net:8000/v1"}).status == 200
        f = _body(get(srv, "/api/insights/providers"))
        assert f["key_present"] is False and f["display"] == "the endpoint at llm.example.net:8000"
        assert _body(get(srv, f"/api/insights/{DAY}"))["reason"] == "No key saved. Add one in Settings › Model."
        assert put(srv, "/api/keys/openai", {"key": "sk-endpoint"}).status == 204
        assert keys.get_key("openai@llm.example.net:8000") == "sk-endpoint" and keys.get_key("openai") == "sk-openai"
        assert _body(get(srv, "/api/insights/providers"))["key_present"] is True
        assert _body(get(srv, f"/api/insights/{DAY}"))["reason"] is None
        assert delete(srv, "/api/keys/openai").status == 204
        assert keys.get_key("openai@llm.example.net:8000") is None and keys.get_key("openai") == "sk-openai"


def test_providers_with_an_unknown_provider_in_config_is_400(server_no_provider):
    server_no_provider.app._app.cfg = dataclasses.replace(server_no_provider.app._app.cfg, insights_provider="nope")
    r = get(server_no_provider, "/api/insights/providers")
    assert r.status == 400 and "nope" in _body(r)["error"]
