import asyncio
import json
import os
import socket

from conftest import APP_CLOCK_MS, get
from fake_pendant import FakePendant
from lavalier.server import ControlServer


async def test_tick_runs_sync_then_process_when_drained(app_env, storage_payloads):
    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    r = await app.tick()
    assert r.outcome == "drained" and app.last_process is not None and app.snapshot()["busy"] is False


async def test_tick_skips_process_when_nothing_drained(app_env):
    app = app_env(FakePendant(pages=(0, 9)))
    assert (await app.tick()).outcome == "skipped" and app.last_process is None


async def test_actions_serialise_with_the_tick(app_env):
    app = app_env(FakePendant())
    results = await asyncio.gather(app.action("mute"), app.tick())
    assert results[0]["state"] == "NOT_RECORDING"
    sessions = [e for e in app.pendant.log if e in ("enter", "exit")]
    assert sessions == ["enter", "exit", "enter", "exit"]          # never two connections at once


async def test_run_loop_polls_on_the_interval_and_stops(app_env):
    app = app_env(FakePendant(), poll_interval_s=600)
    slept = []
    async def fake_sleep(s): slept.append(s); app.stop()
    app._sleep = fake_sleep
    await app.run()
    assert slept == [600] and app.pendant.log.count("status") == 1


def test_app_with_no_provider_runs_with_non_loopback_sockets_blocked(app_env, monkeypatch):
    real_connect = socket.socket.connect
    def guarded(self, addr):
        if addr[0] not in ("127.0.0.1", "localhost"): raise AssertionError(f"network access attempted: {addr}")
        return real_connect(self, addr)
    monkeypatch.setattr(socket.socket, "connect", guarded)
    app = app_env(FakePendant(pages=(0, 9)))
    asyncio.run(app.tick())
    srv = ControlServer(app, token_path=app.paths.root / ".server.json"); srv.start()
    assert json.loads(get(srv, "/api/health").read())["ok"] is True; srv.stop()


async def test_tick_processes_whatever_the_outcome_when_a_capture_came_in(app_env, storage_payloads):
    from lavalier.device import DeviceError
    # the restore fails after the drain: the outcome is an error, but the capture is in and gets processed
    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads, fail_on={"start": DeviceError("boom")}))
    r = await app.tick()
    assert r.outcome == "error" and r.capture is not None and app.last_process is not None


async def test_owner_mute_action_clears_the_recorder_markers(app_env):
    app = app_env(FakePendant())
    app.db.set_status("unmute_pending_since_ms", "5")
    app.db.set_status("muted_by_recorder_since_ms", "5")
    r = await app.action("mute")
    assert r == {"ok": True, "state": "NOT_RECORDING", "error": None}
    assert app.db.get_status("muted_by_owner_since_ms")
    assert app.db.get_status("unmute_pending_since_ms") is None
    assert app.db.get_status("muted_by_recorder_since_ms") is None


async def test_unmute_and_status_live_actions(app_env):
    from conftest import APP_CLOCK_MS
    app = app_env(FakePendant(state="NOT_RECORDING"))
    app.db.set_status("muted_by_owner_since_ms", "5")
    assert (await app.action("unmute"))["state"] == "LISTENING"
    assert app.pendant.log[:2] == ["enter", f"set_time:{APP_CLOCK_MS}"]   # a mutating session sets the clock
    assert app.db.get_status("muted_by_owner_since_ms") is None
    before = len(app.pendant.log)
    live = await app.action("status-live")
    assert live["ok"] is True and live["summary"]["device"]["source"] == "live"
    assert "set_time" not in " ".join(app.pendant.log[before:])           # the live read stays read-only


async def test_mute_action_sets_the_clock_first(app_env):
    from conftest import APP_CLOCK_MS
    app = app_env(FakePendant())
    await app.action("mute")
    assert app.pendant.log[:4] == ["enter", f"set_time:{APP_CLOCK_MS}", "info", "stop"]


async def test_sync_action_returns_the_report_and_the_process(app_env, storage_payloads):
    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    r = await app.action("sync")
    assert r["sync"]["outcome"] == "drained" and r["process"] == "scheduled"
    json.dumps(r)                                                   # JSON-able as returned
    await app.processing_done()
    assert app.last_process is not None


async def test_a_failed_action_is_reported_once(app_env):
    from lavalier.device import DeviceError
    p = FakePendant(fail_on={"stop": DeviceError("timeout")})
    app = app_env(p)
    r = await app.action("mute")
    assert r["ok"] is False and r["error"] == "Device error: timeout" and p.log.count("stop") == 1


async def test_snapshot_has_the_summary_busy_and_next_poll(app_env):
    app = app_env(FakePendant())
    s = app.snapshot()
    assert s["busy"] is False and isinstance(s["next_poll_ms"], int) and "pending_transcripts" in s


async def test_run_writes_the_token_file_and_removes_it_on_stop(app_env):
    app = app_env(FakePendant(pages=(0, 9)))
    token = app.paths.root / ".server.json"
    seen = []
    async def fake_sleep(s):
        seen.append(json.loads(token.read_text())["pid"]); app.stop()
    app._sleep = fake_sleep
    await app.run()
    assert seen == [os.getpid()] and not token.exists() and not (app.paths.root / ".lock").exists()


async def test_sigterm_while_idle_stops_the_loop_cleanly(app_env):
    import signal
    from lavalier.app import _serve
    app = app_env(FakePendant(pages=(0, 9)))
    async def fake_sleep(s):
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(10)
    app._sleep = fake_sleep
    await asyncio.wait_for(_serve(app), 5)
    assert not app.token_path.exists() and app._db is None and app.pendant.log.count("status") == 1


class _HangingPendant(FakePendant):
    """Gets SIGTERM in the middle of its status read, then hangs there."""

    async def status(self):
        import signal
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(10)


async def test_sigterm_during_a_session_releases_the_lock_and_disconnects(app_env):
    from lavalier.app import _serve
    app = app_env(_HangingPendant())
    await asyncio.wait_for(_serve(app), 5)
    assert app.pendant.log[-1] == "exit" and not (app.paths.root / ".lock").exists()
    assert not app.token_path.exists() and app._db is None


async def test_mute_runs_while_the_tick_is_still_processing(app_env, storage_payloads):
    import threading
    from conftest import speech_transcript
    from lavalier.transcribe import FakeTranscriber
    entered, gate = threading.Event(), threading.Event()

    def slow_transcriber(cfg):  # called in the process worker thread, after the device is released
        entered.set()
        gate.wait(10)
        return FakeTranscriber({}, default=speech_transcript())

    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads), transcriber_factory=slow_transcriber)
    tick = asyncio.create_task(app.tick())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert app.busy is False                                   # processing does not hold the device
        r = await app.action("mute")
        assert r["ok"] is True and r["state"] == "NOT_RECORDING"
        assert not tick.done() and app.last_process is None        # the mute finished while processing waited
    finally:
        gate.set()
    assert (await tick).outcome == "drained" and app.last_process is not None
    log = app.pendant.log
    assert log.count("stop") == 2 and log[-2:] == ["status", "exit"]


class _SlowDrainPendant(FakePendant):
    """Yields to the loop between messages and records what the app held when the session closed."""

    def __init__(self, app_holder, **kw):
        super().__init__(**kw)
        self.app_holder = app_holder
        self.at_exit = None

    async def drain(self, *, idle_s):
        async for m in super().drain(idle_s=idle_s):
            await asyncio.sleep(0.01)
            yield m

    async def __aexit__(self, *exc):
        app = self.app_holder[0]
        self.at_exit = {"lock_file": (app.paths.root / ".lock").exists(), "db_open": app._db is not None}
        await super().__aexit__(*exc)


async def test_sigterm_during_an_action_restores_then_releases_then_closes(app_env, storage_payloads):
    import signal
    import threading
    from types import SimpleNamespace
    from conftest import post
    from lavalier.app import _serve
    from lavalier.db import Database

    holder = []
    pendant = _SlowDrainPendant(holder, pages=(0, 9), messages=storage_payloads * 3)
    app = app_env(pendant)
    holder.append(app)
    pendant.on_ack = lambda index: os.kill(os.getpid(), signal.SIGTERM) if index == 11 else None
    replies = []

    async def fake_sleep(s):  # after the first (skipped) tick: ask the app to drain, over HTTP
        pendant.pages = (0, 999)
        info = json.loads(app.token_path.read_text())
        srv = SimpleNamespace(port=info["port"], token=info["token"])
        def call():
            try:
                replies.append(post(srv, "/api/sync"))
            except Exception as e:
                replies.append(e)
        t = threading.Thread(target=call)
        t.start()
        threads.append(t)
        await asyncio.sleep(10)

    threads = []
    app._sleep = fake_sleep
    await asyncio.wait_for(_serve(app), 10)
    for t in threads:  # off the loop: the reply needs the loop to finish the cancelled request
        await asyncio.to_thread(t.join, 5)

    log = pendant.log
    assert "start" in log and log.index("start") > log.index("stop")       # restored before anything closed
    assert pendant.at_exit == {"lock_file": True, "db_open": True}       # the file lock outlived the session
    assert log[-1] == "exit" and not (app.paths.root / ".lock").exists()
    assert app._db is None and not app.token_path.exists()             # the DB closed last
    assert not isinstance(replies[0], Exception), replies
    assert replies[0].status == 503 and json.loads(replies[0].read()) == {"error": "stopping"}
    db = Database(app.paths.db)
    try:
        assert db.last_sync_run().unmute in ("confirmed", "pending")
    finally:
        db.close()


async def test_a_stopping_app_refuses_actions(app_env):
    from lavalier.server import AppStopping
    app = app_env(FakePendant())
    app.stop()
    try:
        await app.action("mute")
    except AppStopping:
        pass
    else:
        raise AssertionError("action ran on a stopping app")
    assert app.pendant is None                                       # no session was opened


async def test_a_tick_waiting_for_the_device_does_not_sync_once_stopping(app_env, storage_payloads):
    holder = []
    pendant = _SlowDrainPendant(holder, pages=(0, 999), messages=storage_payloads * 3)
    app = app_env(pendant)
    holder.append(app)
    pendant.on_ack = lambda index: app.stop() if index == 11 else None
    action = asyncio.create_task(app.action("sync"))
    await asyncio.sleep(0)                       # the action holds the device
    tick = asyncio.create_task(app.tick())       # the poll interval ran out: the tick waits for the device
    await asyncio.wait({action, tick}, timeout=5)
    assert action.cancelled()
    report = tick.result()
    assert (report.outcome, report.reason) == ("skipped", "stopping")
    log = pendant.log
    assert log.count("enter") == 1 and log.count("exit") == 1          # no second session after the stop
    assert log.count("stop") == 1 and log.count("drain") == 1 and "start" in log


class _SecondStopPendant(_SlowDrainPendant):
    """A second stop arrives while the restore is running."""

    async def start_recording(self):
        self.app_holder[0].stop()
        await asyncio.sleep(0.01)
        await super().start_recording()


async def test_a_second_stop_does_not_cancel_a_running_restore(app_env, storage_payloads):
    from lavalier.db import Database
    holder = []
    pendant = _SecondStopPendant(holder, pages=(0, 999), messages=storage_payloads * 3)
    app = app_env(pendant)
    holder.append(app)
    pendant.on_ack = lambda index: app.stop() if index == 11 else None
    action = asyncio.create_task(app.action("sync"))
    await asyncio.wait({action}, timeout=5)
    assert action.cancelled()                                        # cancelled once, nothing raised
    log = pendant.log
    assert "start" in log and log.index("start") > log.index("stop") and log[-1] == "exit"
    db = Database(app.paths.db)
    try:
        assert db.last_sync_run().unmute == "confirmed"
    finally:
        db.close()


# --- final review fixes: timeouts and cancellation never cut processing short (I1) ---

async def test_a_sync_action_past_the_server_timeout_still_lands_its_run(app_env, storage_payloads):
    from conftest import post
    holder = []
    app = app_env(_SlowDrainPendant(holder, pages=(0, 999), messages=storage_payloads * 3))
    holder.append(app)
    srv = ControlServer(app, token_path=app.token_path, action_timeout_s=0.02)
    srv.start()
    try:
        r = await asyncio.to_thread(post, srv, "/api/sync")
        assert r.status == 504 and json.loads(r.read()) == {"error": "timeout"}
        for _ in range(200):
            if app.db.last_sync_run().outcome != "running":
                break
            await asyncio.sleep(0.01)
        assert app.db.last_sync_run().outcome == "drained"
        await app.processing_done()
        assert app.last_process is not None
    finally:
        srv.stop()


async def test_sync_action_schedules_processing_and_returns_before_it(app_env, storage_payloads):
    import threading
    from conftest import speech_transcript
    from lavalier.transcribe import FakeTranscriber
    entered, gate = threading.Event(), threading.Event()

    def slow_transcriber(cfg):
        entered.set()
        gate.wait(10)
        return FakeTranscriber({}, default=speech_transcript())

    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads), transcriber_factory=slow_transcriber)
    try:
        r = await asyncio.wait_for(app.action("sync"), 5)
        assert r["sync"]["outcome"] == "drained" and r["process"] == "scheduled"
        assert await asyncio.to_thread(entered.wait, 5) and app.last_process is None
    finally:
        gate.set()
    await app.processing_done()
    assert app.last_process is not None


async def test_cancelling_the_wait_on_processing_keeps_the_process_lock_until_the_worker_ends(app_env, storage_payloads):
    import threading
    import time
    from lavalier.sync import SyncReport
    app = app_env(FakePendant())
    active, overlaps, started = [0], [], threading.Event()
    gate = threading.Event()

    def fake_process(report):
        active[0] += 1
        overlaps.append(active[0])
        started.set()
        gate.wait(10) if report.reason == "first" else time.sleep(0.01)
        active[0] -= 1
        return None
    app._process = fake_process
    first = asyncio.create_task(app._process_capture(SyncReport("drained", "first", capture=app.paths.root / "a.bin")))
    assert await asyncio.to_thread(started.wait, 5)
    first.cancel()
    await asyncio.sleep(0.01)
    assert app._process_lock.locked()                           # the worker still runs: the lock stays held
    second = asyncio.create_task(app._process_capture(SyncReport("drained", "second", capture=app.paths.root / "b.bin")))
    await asyncio.sleep(0.05)
    assert overlaps == [1]                                      # the second has not started
    gate.set()
    await asyncio.wait_for(second, 5)
    assert overlaps == [1, 1] and not app._process_lock.locked()


async def test_stopping_the_app_after_a_sync_action_does_not_cancel_its_processing(app_env, storage_payloads):
    import threading
    from conftest import speech_transcript
    from lavalier.transcribe import FakeTranscriber
    gate = threading.Event()

    def slow_transcriber(cfg):
        gate.wait(10)
        return FakeTranscriber({}, default=speech_transcript())

    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads), transcriber_factory=slow_transcriber)
    r = await app.action("sync")
    assert r["process"] == "scheduled"
    app.stop()                                                     # cancels actions in flight, not processing
    gate.set()
    await app.processing_done()
    assert app.last_process is not None


async def test_running_sync_rows_are_closed_at_start(app_env, db):
    db.start_sync_run(1); assert db.last_sync_run().outcome == "running"
    app = app_env(FakePendant())
    app._startup_housekeeping()            # the method run() calls before its first tick
    assert db.last_sync_run().outcome == "error" and db.last_sync_run().error == "interrupted"


# --- Plan 3 Task 5: the window's facts and settings ---

def test_app_reloads_config_after_settings_put(server_with_fixture):
    import json
    from conftest import put
    r = put(server_with_fixture, "/api/settings", {"retention_days": 21})
    assert r.status == 200 and json.loads(r.read())["retention_days"] == 21
    assert server_with_fixture.app.cfg.retention_days == 21


def test_a_settings_put_keeps_what_the_window_saved_meanwhile(server_with_fixture):
    import json
    from conftest import put
    from lavalier import settings
    from lavalier.config import load_config
    app = server_with_fixture.app
    path = app.paths.config
    settings.apply(load_config(path), {"window_size": "1280x800"}, path)  # the window, closing
    r = put(server_with_fixture, "/api/settings", {"retention_days": 21})
    assert r.status == 200
    saved = load_config(path)
    assert (saved.retention_days, saved.window_size, saved.pendant_address) == (21, "1280x800", "FAKE")
    assert (app.cfg.retention_days, app.cfg.window_size) == (21, "1280x800")


async def test_snapshot_names_the_app(app_env):
    import os
    from importlib.metadata import version
    app = app_env(FakePendant())
    s = app.snapshot()
    assert s["app"] == {"version": version("lavalier"), "pid": os.getpid(), "started_ms": APP_CLOCK_MS}


def test_app_version_falls_back_when_the_package_is_unknown(monkeypatch):
    import importlib.metadata
    from lavalier import app as app_mod

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(importlib.metadata, "version", missing)
    assert app_mod._package_version() == "0.0.0"


async def test_a_failed_reload_keeps_its_reason(app_env):
    app = app_env(FakePendant())
    app.paths.config.write_text("not [valid")
    assert app.reload_config() is False and "config.toml" in app.config_error
    app.paths.config.write_text("")
    assert app.reload_config() is True and app.config_error is None


# --- retention runs on its own: at start-up, then once a day ---

DAY_MS = 86_400_000


async def test_the_loop_runs_retention_at_start_and_then_once_a_day(app_env):
    app = app_env(FakePendant(), poll_interval_s=6 * 3600)
    clock = [APP_CLOCK_MS]
    app._now_ms = lambda: clock[0]
    ran, turns = [], [0]
    app._retention = lambda: ran.append(clock[0])

    async def fake_sleep(s):
        clock[0] += s * 1000
        turns[0] += 1
        if turns[0] == 9:  # nine turns: 0h .. 48h
            app.stop()
    app._sleep = fake_sleep
    await app.run()
    assert ran == [APP_CLOCK_MS, APP_CLOCK_MS + DAY_MS, APP_CLOCK_MS + 2 * DAY_MS]


async def test_retention_never_runs_beside_a_processing_run(app_env):
    app = app_env(FakePendant())
    ran = []
    app._retention = lambda: ran.append(app._process_lock.locked())
    await app._process_lock.acquire()                # a process is running
    assert await app.retention_if_due() is False and ran == []
    app._process_lock.release()
    assert await app.retention_if_due() is True and ran == [True]  # ran under the lock
    assert not app._process_lock.locked()
    assert await app.retention_if_due() is False and ran == [True]  # not due again for a day


async def test_a_failed_retention_is_logged_and_waits_a_day(app_env, caplog):
    app = app_env(FakePendant())

    def boom():
        raise OSError("disk gone")
    app._retention = boom
    with caplog.at_level("ERROR"):
        assert await app.retention_if_due() is True
    assert "disk gone" in caplog.text and not app._process_lock.locked()
    assert app.next_retention_ms == APP_CLOCK_MS + DAY_MS


async def test_the_retention_worker_deletes_expired_audio_and_rewrites_the_day(app_env, db, seeded_retention_day):
    old = seeded_retention_day[0]
    app = app_env(FakePendant())
    app._now_ms = lambda: old.transcribed_at + 14 * DAY_MS
    db.mark_day_clean(old.day)
    assert await app.retention_if_due() is True
    assert db.clip(old.clip_id).path == "" and (app.paths.days / f"{old.day.isoformat()}.md").exists()


async def test_each_processing_run_leaves_a_distinct_last_process(app_env, storage_payloads):
    """The window refetches when last_process changes; two runs with equal counts must still differ."""
    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    await app.tick()
    first = json.loads(app.db.get_status("last_process"))
    assert first["processed_ms"] == APP_CLOCK_MS
