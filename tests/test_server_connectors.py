import dataclasses
import json
import logging
import threading
import time

import pytest

import fake_notion as fn
from conftest import _serve_real_app, delete, get, post, put
from fake_calendar import FakeCalendarSource
from fake_pendant import FakePendant
from lavalier import server as server_mod
from lavalier.connectors.calendar import Calendar
from lavalier.connectors.notion import NO_TOKEN, Notion
from lavalier.insights import keys

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
def fake_notion():
    return fn.FakeNotionClient()


@pytest.fixture
def calendar():
    return FakeCalendarSource(authorization="not-asked", calendars=[Calendar("work", "Work", None)])


@pytest.fixture
def conn_server(app_env, db, seeded_2026_10_23_subset, fake_notion, calendar, memory_keyring):
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, notion_enabled=True, notion_database_id=fn.DATABASE_ID)
    app.notion_factory = lambda token: Notion(token, client=fake_notion, sleep=lambda s: None)
    app.calendar_source = calendar
    yield from _serve_real_app(app, db)


def test_get_connectors_reads_the_calendar_in_a_thread(conn_server, calendar):
    r = get(conn_server, "/api/connectors")
    assert r.status == 200 and r.getheader("Cache-Control") == "no-store"
    s = _body(r)
    assert s["notion"]["enabled"] is True and s["notion"]["token_present"] is None and s["notion"]["last"] == []
    assert s["calendar"] == {"enabled": False, "authorization": "not-asked", "calendars": [], "chosen": []}
    calendar.status = "allowed"
    s = _body(get(conn_server, "/api/connectors"))
    assert s["calendar"]["calendars"] == [{"identifier": "work", "title": "Work", "colour": None}]


def test_the_connector_routes_need_the_token_and_a_local_origin(conn_server):
    for method, route in (("GET", "/api/connectors"), ("POST", "/api/connectors/notion/check"),
                          ("POST", "/api/connectors/notion/export"), ("POST", "/api/connectors/calendar/access")):
        fn_ = get if method == "GET" else post
        assert fn_(conn_server, route, token=None).status == 401
        assert fn_(conn_server, route, origin="http://evil.example").status == 403


def test_check_returns_the_database_or_400_with_the_notion_text(conn_server, fake_notion):
    r = post(conn_server, "/api/connectors/notion/check")
    assert r.status == 400 and _body(r)["error"] == NO_TOKEN
    keys.set_key("notion", fn.SECRET)
    r = post(conn_server, "/api/connectors/notion/check")
    assert r.status == 200
    info = _body(r)
    assert info["database_id"] == fn.DATABASE_ID and info["title"] == "Journal" and info["missing_properties"]
    fake_notion.visible = False
    r = post(conn_server, "/api/connectors/notion/check")
    assert r.status == 400 and "cannot see this database" in _body(r)["error"]
    assert fn.SECRET not in r.read().decode()


def test_check_past_its_cap_is_504(conn_server, monkeypatch, fake_notion):
    keys.set_key("notion", fn.SECRET)
    gate = threading.Event()
    monkeypatch.setattr(server_mod, "CHECK_TIMEOUT_S", 0.2)
    real = fake_notion.users.me
    fake_notion.users.me = lambda **kw: (gate.wait(10), real(**kw))[1]
    try:
        assert post(conn_server, "/api/connectors/notion/check").status == 504
    finally:
        gate.set()


def test_export_returns_a_job_and_refusals_are_400(conn_server, db):
    r = post(conn_server, "/api/connectors/notion/export", {"day": DAY})
    assert r.status == 202
    j = _wait_job(conn_server, _body(r)["job"])
    assert j["state"] == "error" and j["error"] == NO_TOKEN    # read by the job: unknown until then
    r = post(conn_server, "/api/connectors/notion/export", {"day": DAY})
    assert r.status == 400 and _body(r)["error"] == NO_TOKEN   # now known absent
    put(conn_server, "/api/keys/notion", {"key": fn.SECRET})
    r = post(conn_server, "/api/connectors/notion/export", {"days": 7})
    assert r.status == 202
    j = _wait_job(conn_server, _body(r)["job"])
    assert j["state"] == "done" and j["result"]["done"] == 1
    r = post(conn_server, "/api/connectors/notion/export", {"day": DAY, "force": True})
    assert _wait_job(conn_server, _body(r)["job"])["result"]["done"] == 1


@pytest.mark.parametrize("body", [{}, {"days": 0}, {"days": 366}, {"days": True}, {"days": "3"},
                                  {"day": "yesterday"}, {"day": DAY, "days": 3}, {"day": DAY, "force": "yes"},
                                  {"days": 7, "force": True}, {"days": 7, "force": False}])
def test_a_bad_export_body_is_400(conn_server, body):
    assert post(conn_server, "/api/connectors/notion/export", body).status == 400


def test_a_second_export_is_409(conn_server, fake_notion):
    keys.set_key("notion", fn.SECRET)
    gate = threading.Event()
    real = fake_notion.users.me
    fake_notion.users.me = lambda **kw: (gate.wait(10), real(**kw))[1]
    job = _body(post(conn_server, "/api/connectors/notion/export", {"day": DAY}))["job"]
    try:
        assert post(conn_server, "/api/connectors/notion/export", {"day": DAY}).status == 409
        assert _body(get(conn_server, "/api/connectors"))["notion"]["exporting"] is True
        assert _body(get(conn_server, "/api/status"))["connectors"]["exporting"] is True
    finally:
        gate.set()
    _wait_job(conn_server, job)


def test_export_while_stopping_is_503(conn_server):
    conn_server.app._app._stopping = True
    try:
        assert post(conn_server, "/api/connectors/notion/export", {"day": DAY}).status == 503
    finally:
        conn_server.app._app._stopping = False


def test_calendar_access_requests_it_and_returns_the_status(conn_server, calendar):
    r = post(conn_server, "/api/connectors/calendar/access")
    assert r.status == 200 and _body(r) == {"authorization": "allowed"} and calendar.access_requests == 1


def test_the_access_cap_matches_the_sources_own_wait():
    from lavalier.connectors import calendar as cal
    assert server_mod.ACCESS_TIMEOUT_S == cal.ACCESS_TIMEOUT_S == 120


def test_calendar_access_past_its_cap_is_504(conn_server, calendar, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(server_mod, "ACCESS_TIMEOUT_S", 0.2)
    calendar.request_access = lambda: (gate.wait(10), "allowed")[1]
    try:
        assert post(conn_server, "/api/connectors/calendar/access").status == 504
    finally:
        gate.set()


def test_the_keys_routes_accept_notion_and_update_the_cache(conn_server, memory_keyring, caplog):
    caplog.set_level(logging.DEBUG)
    assert put(conn_server, "/api/keys/notion", {"key": fn.SECRET}).status == 204
    assert keys.get_key("notion") == fn.SECRET
    assert _body(get(conn_server, "/api/connectors"))["notion"]["token_present"] is True
    assert delete(conn_server, "/api/keys/notion").status == 204
    assert keys.get_key("notion") is None
    assert _body(get(conn_server, "/api/connectors"))["notion"]["token_present"] is False
    assert fn.SECRET not in caplog.text
