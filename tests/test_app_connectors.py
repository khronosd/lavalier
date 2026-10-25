import asyncio
import dataclasses
import logging
import threading
from datetime import date

import pytest

import fake_notion as fn
from fake_calendar import FakeCalendarSource
from fake_pendant import FakePendant
from fake_provider import FakeProvider
from lavalier.config import Config
from lavalier.connectors.calendar import Calendar
from lavalier.connectors.export import CONNECTOR, NO_DATABASE, STOPPED
from lavalier.connectors.notion import NO_TOKEN, Notion
from lavalier.insights import keys
from lavalier.jobs import JobRunning
from lavalier.server import AppStopping

DAY = date(2026, 10, 23)


def _on(cfg: Config) -> Config:
    return dataclasses.replace(cfg, notion_enabled=True, notion_database_id=fn.DATABASE_ID)


@pytest.fixture
def notion_app(app_env, db, seeded_2026_10_23_subset, memory_keyring):
    """A real App on the seeded day with Notion on, a token saved and a scripted Notion in place of the SDK."""
    app = app_env(FakePendant())
    app.cfg = _on(app.cfg)
    keys.set_key("notion", fn.SECRET)
    fake = fn.FakeNotionClient()
    app.notion_factory = lambda token: Notion(token, client=fake, sleep=lambda s: None)
    app.fake = fake
    return app


async def _export(app, days, **kw) -> dict:
    jid = app.export_days(days, **kw)
    await app.jobs.wait(jid)
    return app.jobs.get(jid)


async def _wait_export(app) -> dict:
    for _ in range(500):
        jid = app.jobs.running("export")
        if jid is not None:
            await app.jobs.wait(jid)
            return app.jobs.get(jid)
        await asyncio.sleep(0.01)
    raise AssertionError("no export job started")


# --- the export job

async def test_export_days_exports_a_day_then_reports_it_unchanged(notion_app, db):
    app = notion_app
    j = await _export(app, [DAY])
    assert j["state"] == "done" and j["kind"] == "export" and j["key"] == "export"
    assert j["result"]["done"] == 1 and j["result"]["unchanged"] == 0
    assert j["result"]["stopped"] == [] and j["result"]["errors"] == []
    assert j["result"]["days"] == [{"day": "2026-10-23", "outcome": "exported", "error": None}]
    assert db.export(DAY, CONNECTOR).state == "done"
    assert app._key_present["notion"] is True        # the worker noted the token it read
    j = await _export(app, [DAY])
    assert j["result"]["done"] == 0 and j["result"]["unchanged"] == 1
    assert j["result"]["days"][0]["outcome"] == "unchanged"


async def test_export_is_refused_when_off_without_a_database_or_a_known_missing_token(notion_app):
    app = notion_app
    app.cfg = dataclasses.replace(app.cfg, notion_enabled=False)
    with pytest.raises(ValueError, match="off"):
        app.export_days([DAY])
    app.cfg = dataclasses.replace(app.cfg, notion_enabled=True, notion_database_id="")
    with pytest.raises(ValueError) as e:
        app.export_days([DAY])
    assert str(e.value) == NO_DATABASE
    app.cfg = _on(app.cfg)
    app.note_key("notion", False)
    with pytest.raises(ValueError) as e:
        app.export_days([DAY])
    assert str(e.value) == NO_TOKEN
    assert app.fake.calls == []


async def test_a_token_not_known_either_way_is_read_by_prepare(notion_app, memory_keyring):
    app = notion_app
    keys.delete_key("notion")
    j = await _export(app, [DAY])
    assert j["state"] == "error" and j["error"] == NO_TOKEN
    assert app._key_present["notion"] is False and app.fake.calls == []


async def test_a_failing_check_fails_the_job_with_its_text_and_writes_nothing(notion_app, db):
    app = notion_app
    app.fake.visible = False
    j = await _export(app, [DAY])
    assert j["state"] == "error" and "cannot see this database" in j["error"]
    assert fn.SECRET not in j["error"]
    assert app.fake.writes() == [] and db.export(DAY, CONNECTOR) is None


async def test_one_export_at_a_time(notion_app):
    app = notion_app
    gate = threading.Event()
    real = app.notion_factory
    app.notion_factory = lambda token: (gate.wait(10), real(token))[1]
    jid = app.export_days([DAY])
    with pytest.raises(JobRunning):
        app.export_days([DAY])
    gate.set()
    await app.jobs.wait(jid)
    assert app.snapshot()["connectors"] == {"notion_enabled": True, "calendar_enabled": False, "exporting": False}


async def test_a_day_edited_by_hand_is_reported_stopped_and_force_exports_it(notion_app, db):
    app = notion_app
    await _export(app, [DAY])
    block = db.export(DAY, CONNECTOR).block_id
    app.fake.add_owner_block(block, "my own note")
    j = await _export(app, [DAY])
    assert j["result"]["stopped"] == ["2026-10-23"] and j["result"]["done"] == 0
    assert j["result"]["days"] == [{"day": "2026-10-23", "outcome": "stopped", "error": STOPPED}]
    j = await _export(app, [DAY])                     # stays stopped without force
    assert j["result"]["stopped"] == ["2026-10-23"]
    j = await _export(app, [DAY], force=True)
    assert j["result"]["done"] == 1 and db.export(DAY, CONNECTOR).state == "done"


async def test_an_export_error_is_reported_per_day(notion_app):
    app = notion_app
    app.fake.fail("data_sources.query", fn.unauthorized())
    j = await _export(app, [DAY, date(2026, 10, 20)])
    errors = j["result"]["errors"]
    assert [e["day"] for e in errors] == ["2026-10-23", "2026-10-20"]
    assert errors[0]["error"] == "The token was refused" and errors[1]["error"] == "Nothing to export"


async def test_export_recent_takes_the_newest_days_with_speech_oldest_first(notion_app):
    app = notion_app
    seen = []
    app.export_days = lambda days, *, force=False: seen.append((days, force)) or "j"
    assert app.export_recent(7) == "j" and seen == [([DAY], False)]
    for bad in (0, 366, True, "3"):
        with pytest.raises(ValueError):
            app.export_recent(bad)


async def test_nothing_exports_while_the_app_is_stopping(notion_app):
    app = notion_app
    app.stop()
    with pytest.raises(AppStopping):
        app.export_days([DAY])


async def test_the_loop_thread_never_reads_the_keychain_for_notion(notion_app, monkeypatch):
    app = notion_app
    loop_thread = threading.get_ident()
    reads = []

    def guarded(account):
        reads.append(threading.get_ident())
        assert threading.get_ident() != loop_thread, "the Keychain was read on the loop"
        return fn.SECRET
    monkeypatch.setattr(keys, "get_key", guarded)
    await _export(app, [DAY])
    app.connectors_state()
    app.snapshot()
    assert reads and loop_thread not in reads


# --- automatic exports

async def test_a_process_with_notion_on_exports_the_days_it_wrote(notion_app, db, storage_payloads):
    app = notion_app
    app.note_key("notion", True)
    app._pendant_factory = lambda cfg: FakePendant(pages=(0, 999), messages=storage_payloads)
    await app.tick()
    assert app.last_process.days_written == [DAY]
    j = await _wait_export(app)
    assert j["state"] == "done" and j["result"]["done"] == 1
    assert db.export(DAY, CONNECTOR).state == "done"


async def test_no_automatic_export_with_notion_off_or_the_token_not_known_present(notion_app):
    app = notion_app
    app.cfg = dataclasses.replace(app.cfg, notion_enabled=False)
    app.note_key("notion", True)
    app._auto_export([DAY])
    assert app.jobs.running("export") is None
    app.cfg = _on(app.cfg)
    app.note_key("notion", None)                       # not known either way: the automatic run waits
    app._auto_export([DAY])
    assert app.jobs.running("export") is None and app.fake.calls == []


async def test_an_automatic_export_while_one_runs_is_kept_for_later(notion_app, caplog, db):
    app = notion_app
    app.note_key("notion", True)
    gate = threading.Event()
    real = app.notion_factory
    app.notion_factory = lambda token: (gate.wait(10), real(token))[1]
    jid = app.export_days([date(2026, 10, 20)])
    caplog.set_level(logging.DEBUG, logger="lavalier.app")
    app._auto_export([DAY])                            # skipped silently, remembered
    assert app.jobs.running("export") == jid and DAY in app._export_pending
    assert "export already running" in caplog.text
    app.notion_factory = real
    gate.set()
    await app.jobs.wait(jid)
    j = await _wait_export(app)                        # the pending day goes when the running export ends
    assert j["result"]["done"] == 1 and app._export_pending == set()
    assert db.export(DAY, CONNECTOR).state == "done"


async def test_a_day_is_exported_automatically_at_most_once_a_minute(notion_app):
    app = notion_app
    app.note_key("notion", True)
    clock = [1_000_000]
    app._now_ms = lambda: clock[0]
    app._auto_export([DAY])
    await _wait_export(app)
    app._auto_export([DAY])                            # within 60 s: waits
    assert app.jobs.running("export") is None and DAY in app._export_pending
    clock[0] += 60_001
    app._auto_export([])                               # the next trigger takes it
    j = await _wait_export(app)
    assert j["result"]["unchanged"] == 1 and app._export_pending == set()


async def test_an_insight_generated_with_notion_on_is_exported(notion_app, db):
    app = notion_app
    app.cfg = dataclasses.replace(app.cfg, insights_provider="ollama")
    app.provider_factory = lambda cfg: FakeProvider()
    app.note_key("notion", True)
    await app.jobs.wait(app.generate(DAY))
    j = await _wait_export(app)
    assert j["result"]["done"] == 1
    assert "A short pendant test" in db.export(DAY, CONNECTOR).plain_text


async def test_turning_notion_on_reads_the_token_presence_off_the_loop(app_env, memory_keyring):
    app = app_env(FakePendant())
    keys.set_key("notion", "t")
    app.update_settings({"notion_enabled": True})
    app._key_fill.join(5)
    assert app._key_present["notion"] is True


# --- the calendar

async def test_the_calendar_source_is_built_lazily_in_a_worker(app_env):
    app = app_env(FakePendant())
    loop_thread = threading.get_ident()
    built = []
    app.calendar_factory = lambda: built.append(threading.get_ident()) or FakeCalendarSource()
    assert app.calendar_source is None and built == []
    app.connectors_state()
    assert built == []                                 # the loop never builds it
    facts = await asyncio.to_thread(app.calendar_facts)
    assert facts["authorization"] == "allowed" and built and loop_thread not in built
    await asyncio.to_thread(app.calendar_facts)
    assert len(built) == 1


async def test_calendar_facts_list_calendars_only_when_allowed_and_cache_them(app_env):
    app = app_env(FakePendant())
    src = FakeCalendarSource(authorization="not-asked", calendars=[Calendar("work", "Work", "#ff0000")])
    calls = []
    real = src.calendars
    src.calendars = lambda: calls.append(1) or real()
    app.calendar_source = src
    assert app.calendar_facts() == {"authorization": "not-asked", "calendars": []} and calls == []
    assert app.request_calendar_access() == "allowed" and src.access_requests == 1
    facts = app.calendar_facts()
    assert facts["calendars"] == [{"identifier": "work", "title": "Work", "colour": "#ff0000"}]
    app.calendar_facts()
    assert len(calls) == 1                             # cached for a minute


async def test_without_eventkit_the_calendar_reads_unavailable(app_env):
    app = app_env(FakePendant())
    app.calendar_factory = lambda: None
    assert app.calendar_facts() == {"authorization": "unavailable", "calendars": []}
    assert app.request_calendar_access() == "unavailable"


async def test_the_process_worker_passes_the_calendar_source(app_env, db, storage_payloads, seeded_2026_10_23_subset):
    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    app.cfg = dataclasses.replace(app.cfg, calendar_enabled=True)
    src = FakeCalendarSource()
    app.calendar_source = src
    await app.tick()
    assert src.events_calls == [DAY]


async def test_connectors_state_has_the_brief_shape(notion_app, db):
    app = notion_app
    app.cfg = dataclasses.replace(app.cfg, calendar_enabled=True, calendar_ids="work, home")
    await _export(app, [DAY])
    app.note_key("notion", True)
    state = app.connectors_state({"authorization": "allowed", "calendars": [{"identifier": "work"}]})
    n = state["notion"]
    assert n["enabled"] is True and n["database_id"] == fn.DATABASE_ID and n["token_present"] is True
    assert n["exporting"] is False and len(n["last"]) == 1
    assert n["last"][0]["day"] == "2026-10-23" and n["last"][0]["state"] == "done" and "plain_text" not in n["last"][0]
    assert state["calendar"] == {"enabled": True, "authorization": "allowed", "calendars": [{"identifier": "work"}],
                                 "chosen": ["home", "work"]}
    assert fn.SECRET not in str(state)

