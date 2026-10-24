import asyncio
import json
import os
import socket

from conftest import get
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
    app = app_env(FakePendant(state="NOT_RECORDING"))
    app.db.set_status("muted_by_owner_since_ms", "5")
    assert (await app.action("unmute"))["state"] == "LISTENING"
    assert app.db.get_status("muted_by_owner_since_ms") is None
    live = await app.action("status-live")
    assert live["ok"] is True and live["summary"]["device"]["source"] == "live"
    assert "set_time" not in " ".join(app.pendant.log)


async def test_sync_action_returns_the_report_and_the_process(app_env, storage_payloads):
    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    r = await app.action("sync")
    assert r["sync"]["outcome"] == "drained" and r["process"] is not None
    json.dumps(r)                                                   # JSON-able as returned


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
