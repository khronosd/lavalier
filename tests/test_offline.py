import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("inherited", [None, "0"])
def test_transcribe_import_sets_hf_hub_offline(inherited):
    env = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
    if inherited is not None:
        env["HF_HUB_OFFLINE"] = inherited  # an exported opt-out must not survive the import
    out = subprocess.run(
        [sys.executable, "-c",
         "import lavalier.transcribe, huggingface_hub.constants as c; print(c.HF_HUB_OFFLINE)"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "True"


def test_the_loop_with_no_provider_makes_no_network_call(app_env, db, seeded_2026_10_23_subset, monkeypatch):
    import asyncio
    import socket
    from datetime import date, datetime

    from fake_pendant import FakePendant

    app = app_env(FakePendant(pages=(0, 9)))
    app._now_ms = lambda: int(datetime(2026, 10, 25, 12, 0).timestamp() * 1000)   # the day is complete
    app.db.set_status("insights_enabled_at_ms", "0")                                # due, had a provider been chosen
    assert app.cfg.insights_provider == ""

    real_connect = socket.socket.connect

    def loopback_only(self, addr):  # the control server's own loopback is allowed, nothing else
        if not (isinstance(addr, tuple) and addr[0] in ("127.0.0.1", "localhost")):
            raise AssertionError(f"network access attempted: {addr}")
        return real_connect(self, addr)

    def blocked(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)

    async def one_turn():
        assert await app.insights_if_due() is False

        async def stop_after_one_turn(s):
            app.stop()
        app._sleep = stop_after_one_turn
        await app.run()

    asyncio.run(one_turn())
    assert db.insight(date(2026, 10, 23)) is None


class _TouchedCalendar:
    """A calendar source that fails the test if anything reads it."""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(f"the calendar was read: {name}")


def test_the_loop_with_connectors_off_makes_no_network_call_and_reads_no_calendar(
        app_env, db, seeded_2026_10_23_subset, storage_payloads, monkeypatch):
    import asyncio
    import socket

    from fake_pendant import FakePendant

    app = app_env(FakePendant(pages=(0, 999), messages=storage_payloads))   # a drain, so a process runs
    assert not app.cfg.notion_enabled and not app.cfg.calendar_enabled
    source = _TouchedCalendar()
    app.calendar_source = source
    app.note_key("notion", True)                     # a token saved, the connector still off
    built = []
    app.notion_factory = lambda token: built.append(token)

    real_connect = socket.socket.connect

    def loopback_only(self, addr):
        if not (isinstance(addr, tuple) and addr[0] in ("127.0.0.1", "localhost")):
            raise AssertionError(f"network access attempted: {addr}")
        return real_connect(self, addr)

    def blocked(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)

    async def one_turn():
        async def stop_after_one_turn(s):
            app.stop()
        app._sleep = stop_after_one_turn
        await app.run()

    asyncio.run(one_turn())
    assert app.last_process is not None and app.last_process.days_written   # the process ran
    assert source.touched == [] and built == []
    assert "export" not in app.jobs.running_keys()
