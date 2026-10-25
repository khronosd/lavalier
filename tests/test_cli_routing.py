import asyncio
import threading
from contextlib import contextmanager

import pytest

from fake_pendant import FakePendant
from lavalier import cli
from lavalier.server import ControlServer


def test_cli_uses_the_app_when_it_is_running(cli_env, running_fake_server):
    r = cli_env.invoke(["mute"])
    assert running_fake_server.calls == [("POST", "/api/mute")] and r.exit_code == 0


def test_cli_runs_headless_when_the_token_file_is_stale(cli_env, stale_token_file, monkeypatch):
    p = FakePendant(); monkeypatch.setattr(cli, "pendant_factory", lambda cfg: p)
    cli_env.invoke(["mute"]); assert "stop" in p.log


def test_cli_reports_a_busy_app(cli_env, running_fake_server):
    running_fake_server.busy = True
    r = cli_env.invoke(["mute"])
    assert r.exit_code == 1 and "Another process is using the pendant: lavalier app (busy)" in r.output


def _no_headless(cfg):
    raise AssertionError("the CLI went headless while the app was running")


@contextmanager
def serve(app):
    """Run a real App behind a real ControlServer on a loop in a background thread."""
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    srv = ControlServer(app, token_path=app.paths.root / ".server.json", loop=loop)
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()

        async def close():
            app.close()
        asyncio.run_coroutine_threadsafe(close(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
        t.join(10)
        loop.close()


@pytest.mark.parametrize("args, pendant, expected", [
    (["mute"], dict(), "Pendant muted (NOT_RECORDING)\n"),
    (["unmute"], dict(state="NOT_RECORDING"), "Pendant unmuted (LISTENING)\n"),
    (["sync"], dict(pages=(0, -1), state="NOT_RECORDING"), "Sync: skipped (nothing to do)\n"),
])
def test_output_through_the_app_matches_headless(cli_env, app_env, monkeypatch, args, pendant, expected):
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant(**pendant))
    headless = cli_env.invoke(args)
    app = app_env(FakePendant(**pendant))
    monkeypatch.setattr(cli, "pendant_factory", _no_headless)
    with serve(app):
        routed = cli_env.invoke(args)
    assert headless.output == routed.output == expected and routed.exit_code == 0


def test_status_live_through_the_app(cli_env, app_env, monkeypatch):
    app = app_env(FakePendant(pages=(0, 786), soc=94))
    monkeypatch.setattr(cli, "pendant_factory", _no_headless)
    with serve(app):
        r = cli_env.invoke(["status", "--live"])
    assert r.exit_code == 0, r.output
    assert "Pendant: LISTENING as of 0 min ago (live); battery 94%, 787 pages waiting" in r.output
    assert "set_time" not in " ".join(app.pendant.log)


def test_mute_not_confirmed_through_the_app_exits_1(cli_env, app_env, monkeypatch):
    app = app_env(FakePendant(stop_result="LISTENING"))
    monkeypatch.setattr(cli, "pendant_factory", _no_headless)
    with serve(app):
        r = cli_env.invoke(["mute"])
    assert r.exit_code == 1 and "Mute not confirmed: LISTENING" in r.output


def test_a_drain_through_the_app_says_processing_is_scheduled(cli_env, app_env, monkeypatch, storage_payloads):
    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    monkeypatch.setattr(cli, "pendant_factory", _no_headless)
    with serve(app):
        r = cli_env.invoke(["sync"])
    assert r.exit_code == 0, r.output
    assert "Sync: drained" in r.output and "Processing runs in the app; see 'lavalier status'" in r.output


def test_a_504_from_the_app_says_the_action_continues(cli_env, running_fake_server, monkeypatch):
    from lavalier import client
    monkeypatch.setattr(client, "_request", lambda *a, **kw: (504, b'{"error": "timeout"}'))
    monkeypatch.setattr(client, "app_running", lambda token: True)
    r = cli_env.invoke(["sync"])
    assert r.exit_code == 1 and "it continues in the app" in r.output
