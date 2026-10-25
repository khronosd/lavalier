import asyncio
import dataclasses
import logging
import threading
from datetime import date, datetime

import pytest

from conftest import APP_CLOCK_MS, BrokenKeyring, _real_transcript
from fake_pendant import FakePendant
from fake_provider import FakeProvider
from lavalier.insights import keys
from lavalier.insights.providers.anthropic import NO_KEY
from lavalier.jobs import JOB_KEEP_MS, JobRunning, JobTable

DAY = date(2026, 10, 23)
AFTER_DAY = int(datetime(2026, 10, 24, 5, 0).timestamp() * 1000)   # 2026-10-23 is complete at 04:00
ENABLED = int(datetime(2026, 10, 23, 12, 0).timestamp() * 1000)


@pytest.fixture
def insights_app(app_env, db, seeded_2026_10_23_subset):
    """A real App on the seeded day, with ollama chosen and a scripted provider in its place."""
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, insights_provider="ollama")
    fake = FakeProvider()
    app.provider_factory = lambda cfg: fake
    app.fake = fake
    return app


def _due(app):
    app._now_ms = lambda: AFTER_DAY
    app.db.set_status("insights_enabled_at_ms", str(ENABLED))


# --- the job table

async def test_a_job_runs_in_a_thread_and_is_kept_with_its_result():
    clock = [1000]
    jobs = JobTable(lambda: clock[0])
    loop_thread = threading.get_ident()
    jid = jobs.start("generate", "day:2026-10-23", lambda: threading.get_ident())
    assert jobs.get(jid)["state"] == "running" and jobs.running_keys() == ["day:2026-10-23"]
    await jobs.wait(jid)
    j = jobs.get(jid)
    assert j["state"] == "done" and j["result"] != loop_thread and j["error"] is None
    assert set(j) == {"id", "kind", "key", "state", "result", "error", "started_ms", "finished_ms"}
    clock[0] += JOB_KEEP_MS + 1
    assert jobs.get(jid) is None                      # dropped ten minutes after it finished


async def test_a_running_key_refuses_a_second_job_and_a_failure_is_an_error_state():
    jobs = JobTable(lambda: 0)
    gate = threading.Event()
    jid = jobs.start("generate", "day:x", lambda: gate.wait(10))
    with pytest.raises(JobRunning):
        jobs.start("generate", "day:x", lambda: None)
    gate.set()
    await jobs.wait(jid)
    jobs.start("generate", "day:x", lambda: None)     # free again once it finished

    def boom():
        raise RuntimeError("it broke")
    bad = jobs.start("ask", "ask:y", boom)
    await jobs.wait(bad)
    assert jobs.get(bad)["state"] == "error" and jobs.get(bad)["error"] == "it broke"


async def test_a_job_can_wait_for_a_lock_and_always_releases_it():
    jobs = JobTable(lambda: 0)
    lock = asyncio.Lock()
    await lock.acquire()
    ran = []
    jid = jobs.start("generate", "day:x", lambda: ran.append(lock.locked()), lock=lock)
    await asyncio.sleep(0.05)
    assert ran == [] and jobs.get(jid)["state"] == "running"
    lock.release()
    await jobs.wait(jid)
    assert ran == [True] and not lock.locked()

    def boom():
        raise RuntimeError("x")
    await jobs.wait(jobs.start("generate", "day:y", boom, lock=lock))
    assert not lock.locked()


# --- the loop's stage

async def test_insights_if_due_generates_one_due_day_under_the_lock(insights_app, db, caplog):
    app = insights_app
    _due(app)
    gate = threading.Event()
    app.fake.gate = gate
    caplog.set_level(logging.INFO, logger="lavalier.app")
    assert await app.insights_if_due() is True
    assert app._process_lock.locked()                 # held while the worker runs
    assert await app.insights_if_due() is False       # never twice at once
    gate.set()
    await app.jobs.wait(app._insights_job)
    assert not app._process_lock.locked()
    assert db.insight(DAY).state == "done" and app.fake.calls == [("summarize", DAY)]
    assert "insights: 2026-10-23 done by fake-model" in caplog.text
    assert await app.insights_if_due() is False       # nothing due any more


async def test_insights_if_due_skips_when_the_process_lock_is_held(insights_app):
    app = insights_app
    _due(app)
    await app._process_lock.acquire()
    try:
        assert await app.insights_if_due() is False
    finally:
        app._process_lock.release()
    assert app.fake.calls == []


async def test_insights_if_due_logs_a_failure_and_stores_the_error(insights_app, db, caplog):
    app = insights_app
    _due(app)
    app.fake.error = "Ollama is not running"
    caplog.set_level(logging.INFO, logger="lavalier.app")
    assert await app.insights_if_due() is True
    await app.jobs.wait(app._insights_job)
    assert db.insight(DAY).state == "error" and "insights: 2026-10-23 failed: Ollama is not running" in caplog.text


async def test_nothing_is_due_before_a_provider_was_chosen_or_without_one(insights_app):
    app = insights_app
    app._now_ms = lambda: AFTER_DAY
    assert await app.insights_if_due() is False       # no insights_enabled_at_ms
    _due(app)
    app.cfg = dataclasses.replace(app.cfg, insights_provider="")
    assert await app.insights_if_due() is False and app.fake.calls == []


# --- on demand

async def test_generate_waits_for_the_process_lock_and_reports_stored(insights_app, db):
    app = insights_app
    await app._process_lock.acquire()
    jid = app.generate(DAY)
    await asyncio.sleep(0.05)
    assert app.fake.calls == [] and app.jobs.get(jid)["state"] == "running"
    assert app.insights_day(DAY)["state"] == "generating" and app.insights_day(DAY)["job"] == jid
    app._process_lock.release()
    await app.jobs.wait(jid)
    j = app.jobs.get(jid)
    assert j["state"] == "done" and j["kind"] == "generate" and j["key"] == "day:2026-10-23"
    assert j["result"]["stored"] is True and j["result"]["record"]["state"] == "done"
    rec = j["result"]["record"]
    assert rec["day"] == "2026-10-23" and rec["truncated"] is False
    assert rec["insight"]["follow_ups"][0].keys() == {"text", "at_ms", "line_id"}
    assert not app._process_lock.locked()
    again = app.generate(DAY)
    with pytest.raises(JobRunning):
        app.generate(DAY)
    await app.jobs.wait(again)


async def test_a_failed_regenerate_is_not_stored_and_the_done_row_stays(insights_app, db):
    app = insights_app
    await app.jobs.wait(app.generate(DAY))
    app.fake.error = "rate limited"
    jid = app.generate(DAY)
    await app.jobs.wait(jid)
    r = app.jobs.get(jid)["result"]
    assert r["stored"] is False and r["record"]["state"] == "error" and r["record"]["error"] == "rate limited"
    assert db.insight(DAY).state == "done"
    assert app.insights_day(DAY)["state"] == "done"


async def test_generate_refuses_without_a_usable_provider(insights_app, memory_keyring):
    app = insights_app
    app.cfg = dataclasses.replace(app.cfg, insights_provider="")
    with pytest.raises(ValueError, match="^No model chosen.$"):
        app.generate(DAY)
    app.cfg = dataclasses.replace(app.cfg, insights_provider="anthropic")
    app.note_key("anthropic", False)                  # what the key routes or a worker last saw
    with pytest.raises(ValueError) as e:
        app.ask(DAY, "who?")
    assert str(e.value) == NO_KEY and app.insights_day(DAY)["reason"] == NO_KEY
    app.note_key("anthropic", True)
    assert app.insights_day(DAY)["reason"] is None
    app.note_key("anthropic", None, "The Keychain refused: locked")
    assert app.insights_day(DAY)["reason"] == "The Keychain refused: locked"   # shown; on demand re-reads


async def test_a_key_not_known_either_way_is_read_by_the_worker(insights_app, memory_keyring):
    app = insights_app
    app.cfg = dataclasses.replace(app.cfg, insights_provider="anthropic")
    assert app.insights_day(DAY)["reason"] is None    # unknown counts as present
    jid = app.generate(DAY)
    await app.jobs.wait(jid)
    assert app.jobs.get(jid)["state"] == "error" and app.jobs.get(jid)["error"] == NO_KEY
    assert app.insights_day(DAY)["reason"] == NO_KEY  # the worker noted it
    import keyring
    keyring.set_keyring(BrokenKeyring())
    app.note_key("anthropic", None)
    jid = app.ask(DAY, "who?")
    await app.jobs.wait(jid)
    assert app.jobs.get(jid)["error"].startswith("The Keychain refused")
    assert app.insights_day(DAY)["reason"].startswith("The Keychain refused")


async def test_the_loop_thread_never_reads_the_keychain(insights_app, memory_keyring, monkeypatch):
    app = insights_app
    app.cfg = dataclasses.replace(app.cfg, insights_provider="anthropic")
    keys.set_key("anthropic", "sk-test")
    loop_thread = threading.get_ident()
    reads = []

    def guarded_get_key(provider):
        reads.append(threading.get_ident())
        assert threading.get_ident() != loop_thread, "the Keychain was read on the loop"
        return "sk-test"
    monkeypatch.setattr(keys, "get_key", guarded_get_key)
    fake = app.fake
    app.provider_factory = lambda cfg: (keys.get_key(cfg.insights_provider), fake)[1]   # reads, like the real one
    app.insights_day(DAY)
    app.insights_index()
    await app.jobs.wait(app.generate(DAY))
    await app.jobs.wait(app.ask(DAY, "who?"))
    await app.jobs.wait(app.generate_range(5))
    app.snapshot()
    assert reads and loop_thread not in reads


async def test_start_up_fills_the_key_cache_off_the_loop(app_env, memory_keyring):
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, insights_provider="openai")
    async def fake_sleep(s): app.stop()
    app._sleep = fake_sleep
    await app.run()
    app._key_fill.join(5)                             # its own thread, never awaited by run()
    assert app._key_present == {"openai": False}


async def test_ask_takes_no_lock_and_its_result_is_the_answer(insights_app):
    app = insights_app
    app.fake.answer = "You talked about the pendant."
    await app._process_lock.acquire()
    try:
        jid = app.ask(DAY, "  what did I talk about?  ")
        await app.jobs.wait(jid)
    finally:
        app._process_lock.release()
    j = app.jobs.get(jid)
    assert j["kind"] == "ask" and j["key"].startswith("ask:2026-10-23:")
    assert j["result"] == {"answer": "You talked about the pendant."}
    assert app.fake.calls == [("ask", DAY, "what did I talk about?")]
    with pytest.raises(ValueError):
        app.ask(DAY, "   ")


async def test_a_provider_error_in_ask_is_the_job_error(insights_app):
    app = insights_app
    app.fake.error = "Ollama is not running"
    jid = app.ask(DAY, "who?")
    await app.jobs.wait(jid)
    assert app.jobs.get(jid)["state"] == "error" and app.jobs.get(jid)["error"] == "Ollama is not running"


async def test_generate_range_does_the_complete_days_without_a_done_row(insights_app, db):
    app = insights_app
    app._now_ms = lambda: AFTER_DAY
    for bad in (0, 366):
        with pytest.raises(ValueError):
            app.generate_range(bad)
    jid = app.generate_range(30)
    await app.jobs.wait(jid)
    assert app.jobs.get(jid)["result"] == {"done": 1, "errors": []}
    assert db.insight(DAY).state == "done" and not app._process_lock.locked()
    await app.jobs.wait(app.generate_range(30))       # nothing left to do
    assert app.fake.calls == [("summarize", DAY)]


async def test_a_day_that_is_not_complete_is_not_in_a_range(insights_app):
    app = insights_app                                # the clock is the evening of the day itself
    jid = app.generate_range(5)
    await app.jobs.wait(jid)
    assert app.jobs.get(jid)["result"] == {"done": 0, "errors": []} and app.fake.calls == []


# --- reads

async def test_the_index_lists_follow_ups_people_topics_and_days_without(insights_app):
    app = insights_app
    app._now_ms = lambda: AFTER_DAY
    idx = app.insights_index()
    assert idx["follow_ups"] == [] and idx["generating"] == []
    assert [d["day"] for d in idx["days_without"]] == ["2026-10-23"] and idx["days_without"][0]["chars"] > 0
    assert idx["days_without"][0]["error"] is None
    await app.jobs.wait(app.generate(DAY))
    idx = app.insights_index()
    assert idx["days_without"] == []
    assert idx["follow_ups"][0]["day"] == "2026-10-23" and idx["follow_ups"][0]["text"] == "Check that both stars landed"
    assert idx["follow_ups"][0]["line_id"] and idx["follow_ups"][0]["at_ms"]
    assert idx["people"] == [{"name": "Remy", "days": ["2026-10-23"]}]
    assert idx["topics"] == [{"name": "pendant test", "days": ["2026-10-23"]}]


async def test_an_error_row_is_in_days_without_with_its_error(insights_app):
    app = insights_app
    app._now_ms = lambda: AFTER_DAY
    app.fake.error = "rate limited"
    await app.jobs.wait(app.generate(DAY))
    assert app.insights_index()["days_without"][0]["error"] == "rate limited"
    assert app.insights_day(DAY)["state"] == "error"


async def test_the_day_reads_none_with_no_row_and_the_reason_without_speech(insights_app):
    app = insights_app
    assert app.insights_day(DAY) == {"state": "none", "record": None, "reason": None, "job": None}
    assert app.insights_day(date(2020, 1, 1))["reason"] == "Nothing to summarise for this day"


async def test_the_snapshot_carries_the_insights_settings_and_what_is_generating(insights_app):
    app = insights_app
    gate = threading.Event()
    app.fake.gate = gate
    jid = app.generate(DAY)
    s = app.snapshot()["insights"]
    assert s["provider"] == "ollama" and s["auto"] is True and s["generating"] == ["2026-10-23"]
    assert "days_done" in s
    gate.set()
    await app.jobs.wait(jid)
    assert app.snapshot()["insights"]["generating"] == []


async def test_choosing_a_provider_records_when_and_clearing_it_keeps_it(app_env):
    app = app_env(FakePendant())
    assert app.db.get_status("insights_enabled_at_ms") is None
    app.update_settings({"insights_provider": "ollama"})
    assert app.db.get_status("insights_enabled_at_ms") == str(APP_CLOCK_MS)
    app._now_ms = lambda: APP_CLOCK_MS + 5
    app.update_settings({"insights_model": "llama3"})
    assert app.db.get_status("insights_enabled_at_ms") == str(APP_CLOCK_MS)   # unchanged provider
    app.update_settings({"insights_provider": ""})
    assert app.db.get_status("insights_enabled_at_ms") == str(APP_CLOCK_MS)
    app.update_settings({"insights_provider": "anthropic"})
    assert app.db.get_status("insights_enabled_at_ms") == str(APP_CLOCK_MS + 5)


async def test_the_run_loop_calls_the_insights_stage(app_env):
    app = app_env(FakePendant())
    called = []
    async def fake_due():
        called.append(True)
        return False
    app.insights_if_due = fake_due
    async def fake_sleep(s): app.stop()
    app._sleep = fake_sleep
    await app.run()
    assert called == [True]


async def test_the_loop_stages_skip_while_a_generate_job_is_queued_for_the_lock(insights_app):
    app = insights_app
    _due(app)
    await app._process_lock.acquire()
    jid = app.generate(date(2026, 10, 22))            # queued behind the held lock
    app._process_lock.release()                       # the lock reads free; the job is owed it
    assert await app.insights_if_due() is False and await app.retention_if_due() is False
    await app.jobs.wait(jid)
    assert not app._process_lock.locked()


# --- fix round 1

async def test_the_automatic_run_is_a_day_job(insights_app):
    app = insights_app
    _due(app)
    app.fake.gate = threading.Event()
    assert await app.insights_if_due() is True
    assert app.jobs.get(app._insights_job)["kind"] == "auto"
    assert app.insights_day(DAY)["state"] == "generating"
    with pytest.raises(JobRunning):
        app.generate(DAY)
    app.fake.gate.set()
    await app.jobs.wait(app._insights_job)
    assert not app._process_lock.locked()


async def test_an_unexpected_failure_is_not_sent_again_every_turn(insights_app, db):
    app = insights_app
    _due(app)
    def broken(cfg):
        raise RuntimeError("the adapter broke")
    app.provider_factory = broken
    assert await app.insights_if_due() is True
    await app.jobs.wait(app._insights_job)
    assert app.jobs.get(app._insights_job)["state"] == "error" and db.insight(DAY) is None
    assert await app.insights_if_due() is False       # tried once in this process
    assert not app._process_lock.locked()


async def test_auto_waits_for_a_key_and_says_a_keychain_refusal_once(insights_app, caplog):
    app = insights_app
    _due(app)
    app.cfg = dataclasses.replace(app.cfg, insights_provider="anthropic")
    app.note_key("anthropic", False)
    assert await app.insights_if_due() is False and app.fake.calls == []
    app.note_key("anthropic", None, "The Keychain refused: locked")
    caplog.set_level(logging.INFO, logger="lavalier.app")
    assert await app.insights_if_due() is False
    assert await app.insights_if_due() is False
    assert caplog.text.count("insights: 2026-10-23 skipped: The Keychain refused: locked") == 1
    assert app.fake.calls == []


async def test_a_missing_key_found_by_the_worker_is_tried_again_once_one_is_saved(insights_app, db, memory_keyring):
    app = insights_app
    _due(app)
    app.cfg = dataclasses.replace(app.cfg, insights_provider="anthropic")
    assert await app.insights_if_due() is True        # the cache does not know yet: the worker reads it
    await app.jobs.wait(app._insights_job)
    assert app.jobs.get(app._insights_job)["error"] == NO_KEY and db.insight(DAY) is None
    assert await app.insights_if_due() is False       # the cache now says no key
    keys.set_key("anthropic", "sk-test")
    app.note_key("anthropic", True)                   # what the key route does
    assert await app.insights_if_due() is True
    await app.jobs.wait(app._insights_job)
    assert db.insight(DAY).state == "done"


@pytest.fixture
def second_speech_day(db, clip, cfg):
    from lavalier.group import rebuild_day
    first = int(datetime(2026, 10, 22, 15, 0).timestamp() * 1000)
    c = clip(first, first + 16000)
    db.add_clip(dataclasses.replace(c, classification=None, transcribed_at=None))
    db.set_transcript(c.clip_id, _real_transcript(), "speech", first + 60000)
    rebuild_day(db, date(2026, 10, 22), cfg)
    return date(2026, 10, 22)


async def test_a_range_takes_the_lock_one_day_at_a_time(insights_app, second_speech_day):
    app = insights_app
    app._now_ms = lambda: AFTER_DAY
    order = []
    app.fake.gate = threading.Event()
    real = app.fake.summarize
    def summarize(dt):
        order.append(dt.day)
        return real(dt)
    app.fake.summarize = summarize
    jid = app.generate_range(5)
    while not order:
        await asyncio.sleep(0.01)
    async def drain_processing():                     # a processing run queued behind the first day
        async with app._process_lock:
            order.append("processing")
    waiter = asyncio.ensure_future(drain_processing())
    await asyncio.sleep(0.01)
    app.fake.gate.set()
    await app.jobs.wait(jid)
    await waiter
    assert order == [second_speech_day, "processing", DAY]
    assert app.jobs.get(jid)["result"] == {"done": 2, "errors": []} and not app._process_lock.locked()


async def test_nothing_new_starts_while_the_app_is_stopping(insights_app):
    from lavalier.server import AppStopping
    app = insights_app
    _due(app)
    app._stopping = True
    assert await app.insights_if_due() is False
    for start in (lambda: app.generate(DAY), lambda: app.generate_range(3), lambda: app.ask(DAY, "who?")):
        with pytest.raises(AppStopping):
            start()
    assert app.fake.calls == []


def test_day_text_chars_is_one_query_over_speech_segments(db, seeded_2026_10_23_subset):
    assert db.day_text_chars() == {DAY: 2 * len(" test test test one two three")}


async def test_start_up_records_a_provider_chosen_by_hand(app_env):
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, insights_provider="ollama")
    async def fake_sleep(s): app.stop()
    app._sleep = fake_sleep
    await app.run()
    from lavalier.db import Database
    db = Database(app.paths.db)
    try:
        assert db.get_status("insights_enabled_at_ms") == str(APP_CLOCK_MS)
    finally:
        db.close()


async def test_start_up_keeps_an_earlier_enabled_moment_and_none_without_a_provider(app_env):
    app = app_env(FakePendant())
    app.db.set_status("insights_enabled_at_ms", "5")
    app.cfg = dataclasses.replace(app.cfg, insights_provider="ollama")
    app._startup_housekeeping()
    assert app.db.get_status("insights_enabled_at_ms") == "5"
    other = app_env(FakePendant())
    other.db.clear_status("insights_enabled_at_ms")
    other._startup_housekeeping()
    assert other.db.get_status("insights_enabled_at_ms") is None


# --- fix round 2

async def test_start_up_does_not_wait_for_the_key_fill(app_env):
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, insights_provider="openai")
    release = threading.Event()
    def stuck_fill(provider):   # a Keychain prompt nobody answers
        release.wait(10)
    app._read_key_presence = stuck_fill
    async def fake_sleep(s): app.stop()
    app._sleep = fake_sleep
    try:
        await asyncio.wait_for(app.run(), 5)
        assert app.pendant.log.count("status") == 1   # the first tick ran
    finally:
        release.set()


async def test_a_cached_keychain_error_does_not_refuse_an_on_demand_run(insights_app, memory_keyring):
    app = insights_app
    app.cfg = dataclasses.replace(app.cfg, insights_provider="anthropic")
    keys.set_key("anthropic", "sk-test")              # the Keychain answers again
    app.note_key("anthropic", None, "The Keychain refused: locked")
    assert app.insights_day(DAY)["reason"].startswith("The Keychain refused")   # still shown
    jid = app.generate(DAY)
    await app.jobs.wait(jid)
    assert app.jobs.get(jid)["state"] == "done"
    assert app.insights_day(DAY)["reason"] is None    # the worker's read cleared it
    app.note_key("anthropic", None, "The Keychain refused: locked")
    await app.jobs.wait(app.ask(DAY, "who?"))


async def test_an_older_worker_read_never_overwrites_a_newer_route_write(insights_app):
    app = insights_app
    seen = app._key_seen("anthropic")                 # a worker starts its read
    app.note_key("anthropic", True)                   # a key PUT lands meanwhile
    app.note_key("anthropic", False, seen=seen)       # the worker's older answer
    assert app._key_present["anthropic"] is True
    app.note_key("anthropic", False, seen=app._key_seen("anthropic"))
    assert app._key_present["anthropic"] is False


async def test_changing_the_model_lets_auto_try_attempted_days_again(insights_app):
    app = insights_app
    app._attempted.add(DAY)
    app.update_settings({"insights_auto": False})
    assert DAY in app._attempted
    app.update_settings({"insights_model": "llama3"})
    assert app._attempted == set()
    app._attempted.add(DAY)
    app.update_settings({"insights_base_url": "http://localhost:1"})
    assert app._attempted == set()
    app._attempted.add(DAY)
    app.update_settings({"insights_provider": "anthropic"})
    assert app._attempted == set()


async def test_an_error_row_reports_the_chars_it_sent(insights_app, db):
    app = insights_app
    app._now_ms = lambda: AFTER_DAY
    app.fake.error = "rate limited"
    await app.jobs.wait(app.generate(DAY))
    row = app.insights_index()["days_without"][0]
    assert row["chars"] == db.insight(DAY).input_chars
