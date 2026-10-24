import hashlib
import logging
from dataclasses import replace

import pytest

from builders import make_audio_flash_page, make_storage_buffer_msg
from fake_pendant import FakePendant
from lavalier.charger import ChargerDecision
from lavalier.capture import CaptureSink
from lavalier.device import DeviceError, LinkDropped
from lavalier.lock import LockHeld, SyncLock
from lavalier.models import DeviceSnapshot
from lavalier.sync import UNMUTE_PENDING_MAX_MS, SyncReport, after_sync, decide_drain, run_sync
from lavalier.transcribe import FakeTranscriber


class _SyncEnv:
    def __init__(self, root, db, cfg):
        self._paths, self._db, self._cfg = root, db, cfg
        self.clock = 1_000_000
        self.root = root.root

    async def __call__(self, pendant, **overrides):
        kw = dict(
            cfg=self._cfg,
            lock=SyncLock(self.root / ".lock", list_processes=lambda: []),
            cdc_present=lambda: False,
            dry_run=False,
        )
        unknown = set(overrides) - set(kw)
        assert not unknown, unknown
        kw.update(overrides)
        cfg = kw.pop("cfg")
        return await run_sync(self._db, self._paths, cfg, pendant, now_ms=lambda: self.clock,
                              settle_s=0, **kw)


@pytest.fixture
def sync_env(root, db, cfg):
    return _SyncEnv(root, db, cfg)


# --- the brief's tests, verbatim ---

async def test_not_in_range_sends_nothing(sync_env):
    p = FakePendant(in_range=False)
    r = await sync_env(p)
    assert r.outcome == "not-in-range" and p.log == []

async def test_poll_sets_time_first_then_reads_and_persists(sync_env, db):
    p = FakePendant(pages=(0, 99))
    r = await sync_env(p)
    assert p.log[:4] == ["enter", "set_time:1000000", "info", "status"]
    assert r.outcome == "skipped" and r.reason == "nothing to do"
    snap, source, signal = db.latest_device_status()
    assert (snap.firmware_ver, snap.pages_waiting, source, signal) == ("1.1.3", 100, "sync", "none")
    assert db.last_sync_run().outcome == "skipped"

@pytest.mark.parametrize("kw,cdc,reason", [
    (dict(pages=(0, 999)), False, "pages waiting 1000 >= 1000"),
    (dict(pages=(0, 9)), True, "on charger (usb-cdc)"),
    (dict(pages=(0, 9), current_ma=51), False, "on charger (current)"),
])
async def test_drain_triggers(sync_env, kw, cdc, reason, storage_payloads):
    p = FakePendant(messages=storage_payloads, **kw)
    r = await sync_env(p, cdc_present=lambda: cdc)
    assert r.outcome == "drained" and r.reason == reason

async def test_drain_after_24h_without_one(sync_env, db, storage_payloads):
    r1 = db.start_sync_run(0); db.finish_sync_run(r1, ended_ms=1, outcome="drained", reason="", pages=1, messages=1, capture_id=None, muted_by=None, unmute="n/a", error=None)
    sync_env.clock = 1 + 25 * 3600 * 1000
    r = await sync_env(FakePendant(pages=(0, 9), messages=storage_payloads))
    assert r.outcome == "drained" and r.reason == "last drain 25h ago"

async def test_two_quiet_polls_count_as_on_charger(sync_env, storage_payloads):
    p = FakePendant(pages=(0, 9), messages=storage_payloads)
    assert (await sync_env(p)).outcome == "skipped"
    r = await sync_env(p)
    assert r.outcome == "drained" and r.reason == "on charger (quiet-polls)"

async def test_mute_drain_restore_in_order(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads)
    r = await sync_env(p)
    assert [e for e in p.log if not e.startswith("ack")] == ["enter", "set_time:1000000", "info", "status", "stop", "status", "drain", "start", "status", "exit"]
    assert (r.muted_by, r.unmute, r.pages) == ("recorder", "confirmed", len(storage_payloads))
    assert db.get_status("muted_by_recorder_since_ms") is None and r.capture.exists()
    assert db.capture_by_sha(hashlib.sha256(r.capture.read_bytes()).hexdigest()) is not None

async def test_owner_mute_is_left_alone(sync_env, storage_payloads):
    p = FakePendant(state="NOT_RECORDING", pages=(0, 999), messages=storage_payloads)
    r = await sync_env(p)
    assert "stop" not in p.log and "start" not in p.log and (r.muted_by, r.unmute) == ("owner", "owner-mute-left")

async def test_partial_status_drains_by_pages_but_never_mutes(sync_env, storage_payloads):
    p = FakePendant(partial=True, pages=(0, 999), messages=storage_payloads)
    r = await sync_env(p)
    assert r.outcome == "drained" and "partial status, no mute" in r.reason and "stop" not in p.log and "start" not in p.log

async def test_unconfirmed_mute_aborts_without_retry(sync_env, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, stop_result="LISTENING")
    r = await sync_env(p)
    assert r.outcome == "error" and r.error == "mute not confirmed: LISTENING" and p.log.count("stop") == 1 and "drain" not in p.log

async def test_link_drop_mid_drain_keeps_capture_and_marks_unmute_pending(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, disconnect_after=1)
    r = await sync_env(p)
    assert r.outcome == "drained" and r.capture_complete is False and r.pages == 1 and r.unmute == "pending"
    assert db.get_status("unmute_pending_since_ms") == "1000000"

async def test_pending_unmute_is_retried_once_when_young(sync_env, db):
    db.set_status("unmute_pending_since_ms", "1000000"); db.set_status("muted_by_recorder_since_ms", "999000")
    sync_env.clock = 1000000 + 10 * 60 * 1000
    p = FakePendant(state="NOT_RECORDING", pages=(0, 9))
    r = await sync_env(p)
    assert p.log[4:6] == ["start", "status"] and r.unmute == "retried" and db.get_status("unmute_pending_since_ms") is None

async def test_pending_unmute_is_left_alone_when_old(sync_env, db):
    db.set_status("unmute_pending_since_ms", "1000000")
    sync_env.clock = 1000000 + UNMUTE_PENDING_MAX_MS
    p = FakePendant(state="NOT_RECORDING", pages=(0, 9))
    r = await sync_env(p)
    assert "start" not in p.log and "unmute pending since" in r.reason and db.get_status("unmute_pending_since_ms") == "1000000"

async def test_forced_recording_after_unmute_is_reported(sync_env, storage_payloads, caplog):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, start_result="RECORDING")
    r = await sync_env(p)
    assert r.unmute == "confirmed-recording" and "forced recording" in caplog.text

async def test_firmware_change_warns_and_required_firmware_refuses(sync_env, db, cfg, storage_payloads, caplog):
    db.set_status("last_firmware_ver", "1.1.3")
    r = await sync_env(FakePendant(firmware="1.1.20", pages=(0, 9)))
    assert r.outcome == "skipped" and "firmware changed 1.1.3 -> 1.1.20" in caplog.text
    r2 = await sync_env(FakePendant(firmware="1.1.20", pages=(0, 999), messages=storage_payloads), cfg=replace(cfg, require_firmware="1.1.3"))
    assert r2.outcome == "refused" and r2.reason == "firmware 1.1.20 != required 1.1.3" and db.latest_device_status()[0].firmware_ver == "1.1.20"

async def test_dry_run_decides_but_does_not_touch(sync_env, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads)
    r = await sync_env(p, dry_run=True)
    assert r.outcome == "dry-run" and r.reason == "would drain: pages waiting 1000 >= 1000"
    assert p.log == ["enter", "set_time:1000000", "info", "status", "exit"]

async def test_lock_held_means_no_connection(sync_env):
    p = FakePendant()
    r = await sync_env(p, lock=SyncLock(sync_env.root / ".lock", list_processes=lambda: [(9, "/x/bin/pendant status")]))
    assert r.outcome == "locked" and p.log == []

async def test_after_sync_processes_only_a_drain(root, db, cfg):
    assert after_sync(db, root, cfg, SyncReport("skipped", "nothing to do"), FakeTranscriber({}), now_ms=0) is None


# --- further behaviour ---

class _LostLock:
    """A lock that is taken fine but reports itself lost at the first heartbeat."""

    def __init__(self):
        self.released = False

    def acquire(self):
        pass

    def heartbeat(self):
        raise LockHeld("lost: pid 42")

    def release(self):
        self.released = True


class _FailingPendant(FakePendant):
    """Raises a non-link DeviceError after the first message of the drain."""

    async def drain(self, *, idle_s):
        async for i, m in _enumerate(super().drain(idle_s=idle_s)):
            if i == 1:
                raise DeviceError("timeout")
            yield m


async def _enumerate(agen):
    i = 0
    async for x in agen:
        yield i, x
        i += 1


def _snap(**kw):
    base = DeviceSnapshot(1, True, "LISTENING", 0, 9, 90, -10, "USB_DISCONNECTED", "1.1.3", 7)
    return replace(base, **kw)


@pytest.mark.parametrize("snap_kw,charger,last,now,expected", [
    ({}, ChargerDecision(True, "current"), None, 0, (True, "on charger (current)")),
    (dict(newest_page=998), ChargerDecision(False, "none"), None, 0, (False, "nothing to do")),
    (dict(newest_page=999), ChargerDecision(False, "none"), None, 0, (True, "pages waiting 1000 >= 1000")),
    ({}, ChargerDecision(False, "none"), 0, 24 * 3600 * 1000, (False, "nothing to do")),
    ({}, ChargerDecision(False, "none"), 0, 24 * 3600 * 1000 + 1, (True, "last drain 24h ago")),
])
def test_decide_drain_first_match_and_boundaries(cfg, snap_kw, charger, last, now, expected):
    assert decide_drain(_snap(**snap_kw), charger, last, now_ms=now, cfg=cfg) == expected


async def test_every_run_is_finished_and_the_lock_released(sync_env, db):
    for p in (FakePendant(in_range=False), FakePendant(pages=(0, 9))):
        r = await sync_env(p)
        run = db.last_sync_run()
        assert (run.outcome, run.ended_ms) == (r.outcome, 1_000_000)
        assert not (sync_env.root / ".lock").exists()


async def test_locked_run_is_recorded_with_the_holder(sync_env, db):
    r = await sync_env(FakePendant(), lock=SyncLock(sync_env.root / ".lock", list_processes=lambda: [(9, "/x/bin/pendant status")]))
    assert "pendant status" in r.reason and db.last_sync_run().outcome == "locked"


async def test_not_in_range_resets_quiet_polls_and_keeps_last_seen(sync_env, db):
    await sync_env(FakePendant(pages=(0, 9)))
    assert db.get_status("quiet_polls") == "1" and db.get_status("last_seen_ms") == "1000000"
    sync_env.clock = 2_000_000
    await sync_env(FakePendant(in_range=False))
    assert db.get_status("quiet_polls") == "0" and db.get_status("last_seen_ms") == "1000000"


async def test_quiet_polls_reset_after_a_drain_and_when_not_listening(sync_env, db, storage_payloads):
    await sync_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    assert db.get_status("quiet_polls") == "0"
    await sync_env(FakePendant(pages=(0, 9)))
    await sync_env(FakePendant(state="NOT_RECORDING", pages=(0, 9)))
    assert db.get_status("quiet_polls") == "0"


async def test_young_pending_unmute_still_muted_keeps_the_flag(sync_env, db):
    db.set_status("unmute_pending_since_ms", "1000000")
    sync_env.clock = 1000000 + 60 * 1000
    p = FakePendant(state="NOT_RECORDING", pages=(0, 9), start_result="NOT_RECORDING")
    r = await sync_env(p)
    assert p.log.count("start") == 1 and r.unmute == "n/a" and db.get_status("unmute_pending_since_ms") == "1000000"


async def test_pending_unmute_skipped_on_partial_status(sync_env, db):
    db.set_status("unmute_pending_since_ms", "1000000")
    p = FakePendant(partial=True, pages=(0, 9))
    r = await sync_env(p)
    assert "start" not in p.log and r.outcome == "skipped"


async def test_dry_run_skips_the_pending_unmute_too(sync_env, db):
    db.set_status("unmute_pending_since_ms", "1000000")
    p = FakePendant(state="NOT_RECORDING", pages=(0, 9))
    r = await sync_env(p, dry_run=True)
    assert r.outcome == "skipped" and p.log == ["enter", "set_time:1000000", "info", "status", "exit"]


async def test_lock_lost_mid_drain_stops_imports_and_still_restores(sync_env, db, storage_payloads):
    lock = _LostLock()
    p = FakePendant(pages=(0, 999), messages=storage_payloads * 40)
    r = await sync_env(p, lock=lock)
    assert r.outcome == "error" and r.error == "lost: pid 42" and lock.released
    assert r.messages == 100 and r.capture_complete is False and r.capture.exists()
    assert [e for e in p.log if not e.startswith("ack")][-3:] == ["start", "status", "exit"] and r.unmute == "confirmed"
    assert db.last_sync_run().error == "lost: pid 42"


async def test_other_device_error_mid_drain_keeps_capture_and_records_error(sync_env, db, storage_payloads):
    p = _FailingPendant(pages=(0, 999), messages=storage_payloads)
    r = await sync_env(p)
    assert r.outcome == "error" and r.error == "timeout" and r.capture_complete is False and r.pages == 1
    assert r.unmute == "confirmed" and db.capture_by_sha(hashlib.sha256(r.capture.read_bytes()).hexdigest()) is not None


async def test_unexpected_exception_is_an_error_and_releases_the_lock(sync_env, db):
    class Boom(FakePendant):
        async def info(self):
            raise RuntimeError("boom")
    r = await sync_env(Boom(pages=(0, 9)))
    assert (r.outcome, r.error) == ("error", "boom") and db.last_sync_run().error == "boom"
    assert not (sync_env.root / ".lock").exists()


async def test_report_json_is_plain(sync_env, storage_payloads):
    r = await sync_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    d = r.to_json_dict()
    assert d["capture"] == str(r.capture) and d["status"]["recording_state"] == "LISTENING" and d["outcome"] == "drained"


def test_after_sync_processes_a_drain(root, db, cfg, tmp_path):
    report = after_sync(db, root, cfg, SyncReport("drained", "on charger (current)", capture=tmp_path / "c.bin"),
                        FakeTranscriber({}, unavailable="test"), now_ms=0)
    assert report is not None and report.transcribed == 0


def test_after_sync_processes_a_capture_even_when_the_outcome_is_error(root, db, cfg, tmp_path):
    report = after_sync(db, root, cfg, SyncReport("error", "x", capture=tmp_path / "c.bin", error="timeout"),
                        FakeTranscriber({}, unavailable="test"), now_ms=0)
    assert report is not None


async def test_unwrapped_exception_in_restore_leaves_the_pending_flag(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, fail_on={"start": ValueError("boom")})
    r = await sync_env(p)
    assert r.outcome == "error" and "boom" in r.error
    assert db.get_status("unmute_pending_since_ms") == "1000000"
    assert db.get_status("muted_by_recorder_since_ms") == "1000000"


def test_after_sync_skips_a_drain_that_brought_nothing(root, db, cfg):
    assert after_sync(db, root, cfg, SyncReport("drained", "on charger (usb-cdc)"), FakeTranscriber({}), now_ms=0) is None


async def test_pending_flag_cleared_when_pendant_is_already_listening(sync_env, db, caplog):
    caplog.set_level(logging.INFO, logger="lavalier.sync")
    db.set_status("unmute_pending_since_ms", "1"); db.set_status("muted_by_recorder_since_ms", "1")
    p = FakePendant(state="LISTENING", pages=(0, 9))
    r = await sync_env(p)
    assert r.outcome == "skipped" and "start" not in p.log and "unmute pending since" not in r.reason
    assert db.get_status("unmute_pending_since_ms") is None and db.get_status("muted_by_recorder_since_ms") is None
    assert "unmute pending cleared: pendant is LISTENING" in caplog.text


async def test_confirmed_restore_clears_a_pending_flag(sync_env, db, storage_payloads):
    db.set_status("unmute_pending_since_ms", "1")
    p = FakePendant(pages=(0, 999), messages=storage_payloads)
    r = await sync_env(p)
    assert (r.muted_by, r.unmute) == ("recorder", "confirmed")
    assert db.get_status("unmute_pending_since_ms") is None and db.get_status("muted_by_recorder_since_ms") is None


@pytest.mark.parametrize("start_result,unmute", [("LISTENING", "confirmed"), ("RECORDING", "confirmed-recording")])
async def test_confirmed_restore_clears_a_flag_set_during_the_drain(sync_env, db, storage_payloads, start_result, unmute):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, start_result=start_result)
    p.on_ack = lambda index: db.set_status("unmute_pending_since_ms", "1")  # step 3 cannot see this one
    r = await sync_env(p)
    assert r.unmute == unmute and db.get_status("unmute_pending_since_ms") is None
    assert db.get_status("muted_by_recorder_since_ms") is None


async def test_drained_run_leaves_one_canonical_capture(sync_env, db, storage_payloads):
    r = await sync_env(FakePendant(pages=(0, 999), messages=storage_payloads))
    files = list((sync_env.root / "captures").iterdir())
    assert files == [r.capture]
    assert db.capture_by_sha(hashlib.sha256(r.capture.read_bytes()).hexdigest()) is not None


async def test_failed_import_keeps_the_sink_file_and_restores(sync_env, db, storage_payloads, monkeypatch):
    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr("lavalier.sync.import_and_decode", boom)
    p = FakePendant(pages=(0, 999), messages=storage_payloads)
    r = await sync_env(p)
    assert (r.outcome, r.error, r.unmute) == ("error", "disk full", "confirmed")
    assert r.capture.exists() and list((sync_env.root / "captures").iterdir()) == [r.capture]


# --- review fix round 1 ---

def _commands(p):
    return [e for e in p.log if not e.startswith("ack")]


async def _next_poll_retries_the_unmute(sync_env, db):
    sync_env.clock = 1_000_000 + 60 * 1000
    p = FakePendant(state="NOT_RECORDING", pages=(0, 9))
    r = await sync_env(p)
    assert p.log.count("start") == 1 and r.unmute == "retried" and r.muted_by is None
    assert db.get_status("unmute_pending_since_ms") is None


async def test_stop_that_drops_the_link_leaves_a_pending_unmute(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, fail_on={"stop": LinkDropped("link dropped")})
    r = await sync_env(p)
    assert r.outcome == "error" and r.error == "link dropped" and r.unmute == "pending"
    assert _commands(p) == ["enter", "set_time:1000000", "info", "status", "stop", "exit"]
    assert db.get_status("unmute_pending_since_ms") == "1000000" and db.get_status("muted_by_recorder_since_ms") == "1000000"
    await _next_poll_retries_the_unmute(sync_env, db)


async def test_failed_read_after_stop_restores_while_the_link_is_alive(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, fail_on={"status#2": DeviceError("timeout")})
    r = await sync_env(p)
    assert r.outcome == "error" and r.error == "timeout" and r.unmute == "confirmed"
    assert _commands(p) == ["enter", "set_time:1000000", "info", "status", "stop", "status", "start", "status", "exit"]
    assert db.get_status("unmute_pending_since_ms") is None and db.get_status("muted_by_recorder_since_ms") is None


async def test_failed_read_after_stop_then_lost_link_leaves_a_pending_unmute(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads,
                    fail_on={"status#2": DeviceError("timeout"), "start": LinkDropped("link dropped")})
    r = await sync_env(p)
    assert r.outcome == "error" and r.error == "timeout" and r.unmute == "pending" and "drain" not in p.log
    assert db.get_status("unmute_pending_since_ms") == "1000000"
    await _next_poll_retries_the_unmute(sync_env, db)


async def test_partial_status_after_stop_is_not_a_confirmed_mute(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, partial_after_stop=True)
    r = await sync_env(p)
    assert r.outcome == "error" and r.error == "mute not confirmed: partial status" and "drain" not in p.log
    assert r.unmute == "pending" and db.get_status("unmute_pending_since_ms") == "1000000"


async def test_partial_status_after_restore_is_pending(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads)
    real_start = p.start_recording
    async def start_then_partial():
        await real_start()
        p.partial = True
    p.start_recording = start_then_partial
    r = await sync_env(p)
    assert r.outcome == "drained" and r.unmute == "pending" and db.get_status("unmute_pending_since_ms") == "1000000"


async def test_partial_status_after_pending_retry_keeps_the_flag(sync_env, db):
    db.set_status("unmute_pending_since_ms", "1000000")
    p = FakePendant(state="NOT_RECORDING", pages=(0, 9), start_result="LISTENING")
    real_start = p.start_recording
    async def start_then_partial():
        await real_start()
        p.partial = True
    p.start_recording = start_then_partial
    r = await sync_env(p)
    assert r.unmute == "n/a" and db.get_status("unmute_pending_since_ms") == "1000000"


async def test_restore_device_error_is_recorded(sync_env, db, storage_payloads):
    p = FakePendant(pages=(0, 999), messages=storage_payloads, fail_on={"start": DeviceError("timeout")})
    r = await sync_env(p)
    assert (r.outcome, r.unmute) == ("error", "pending") and "timeout" in r.error
    assert db.get_status("unmute_pending_since_ms") == "1000000" and db.last_sync_run().error == r.error


async def test_full_listening_status_clears_a_stale_mute_marker(sync_env, db):
    db.set_status("muted_by_recorder_since_ms", "5")
    await sync_env(FakePendant(pages=(0, 9)))
    assert db.get_status("muted_by_recorder_since_ms") is None


async def test_sink_failure_mid_drain_imports_what_was_written(sync_env, db, storage_payloads, monkeypatch):
    real_add = CaptureSink.add
    calls = {"n": 0}
    def add(self, payload):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real_add(self, payload)
    monkeypatch.setattr(CaptureSink, "add", add)
    p = FakePendant(pages=(0, 999), messages=storage_payloads)
    r = await sync_env(p)
    assert (r.outcome, r.error, r.unmute) == ("error", "disk full", "confirmed")
    assert r.pages == 1 and r.capture_complete is False
    assert db._conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1


async def test_sink_close_failure_does_not_hide_the_drain_error(sync_env, db, storage_payloads, monkeypatch):
    real_close = CaptureSink.close
    def close(self, *, complete):
        real_close(self, complete=complete)  # the handle is released; the failure is reported after
        raise OSError("close failed")
    monkeypatch.setattr(CaptureSink, "close", close)
    p = FakePendant(pages=(0, 999), messages=storage_payloads, disconnect_after=1)
    r = await sync_env(p)
    assert r.outcome == "error" and r.error == "capture close failed: close failed" and r.unmute == "pending"
    assert len(list((sync_env.root / "captures").iterdir())) == 1  # left on disk, never deleted
