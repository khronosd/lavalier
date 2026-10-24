import logging
from datetime import datetime

import pytest

from fake_pendant import FakePendant
from lavalier import cli
from lavalier.device import DeviceError

_T = datetime.fromtimestamp(1792821367.981).strftime("%Y-%m-%d %H:%M")  # local time, as status prints it


def test_sync_dry_run_prints_the_decision(cli_env, monkeypatch):
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant(pages=(0, 999)))
    r = cli_env.invoke(["sync", "--dry-run"])
    assert r.exit_code == 0 and "Sync: dry-run (would drain: pages waiting 1000 >= 1000)" in r.output


def test_sync_requires_an_address(cli_env_no_address):
    r = cli_env_no_address.invoke(["sync"])
    assert r.exit_code == 1 and "set pendant_address" in r.output


def test_sync_skipped_exits_0(cli_env, monkeypatch):
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant(pages=(0, 9)))
    r = cli_env.invoke(["sync"])
    assert r.exit_code == 0 and "Sync: skipped (nothing to do)" in r.output


def test_sync_refused_exits_1(cli_env, monkeypatch, db_at_root):
    from lavalier.config import Config, save_config
    save_config(Config(pendant_address="FAKE", require_firmware="9.9.9"), cli_env.root.config)
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant())
    r = cli_env.invoke(["sync"])
    assert r.exit_code == 1 and "Sync: refused" in r.output


def test_sync_drains_and_processes_a_capture(cli_env, monkeypatch, storage_payloads):
    from lavalier.transcribe import FakeTranscriber
    p = FakePendant(pages=(0, 999), messages=storage_payloads)
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: p)
    monkeypatch.setattr(cli, "MlxWhisperTranscriber", lambda m, l: FakeTranscriber({}, unavailable="test"))
    r = cli_env.invoke(["sync"])
    assert r.exit_code == 0, r.output
    assert "Sync: drained (pages waiting 1000 >= 1000); 3 messages" in r.output
    assert "muted by recorder, unmute confirmed" in r.output and "Transcribed 0" in r.output


def test_sync_reports_another_process_holding_the_lock(cli_env, monkeypatch):
    from lavalier.lock import SyncLock
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant())
    monkeypatch.setattr(cli, "SyncLock", lambda path: SyncLock(path, list_processes=lambda: [(9, "/x/bin/pendant y")]))
    r = cli_env.invoke(["sync"])
    assert r.exit_code == 1 and "Another process is using the pendant: process: /x/bin/pendant y" in r.output


def test_status_live_reads_without_setting_time(cli_env, monkeypatch):
    p = FakePendant(pages=(0, 786), soc=94)
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: p)
    r = cli_env.invoke(["status", "--live"])
    assert "Pendant: LISTENING as of 0 min ago (live); battery 94%, 787 pages waiting" in r.output
    assert "charger: none, firmware 1.1.3" in r.output
    assert "set_time" not in " ".join(p.log)


def test_status_without_a_read_says_so(cli_env):
    assert "Pendant: no status read yet" in cli_env.invoke(["status"]).output


def test_status_live_not_in_range_falls_back_to_the_last_read(cli_env, monkeypatch):
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant(in_range=False))
    r = cli_env.invoke(["status", "--live"])
    assert r.exit_code == 0 and "not in range" in r.output and "Pendant: no status read yet" in r.output


def test_mute_and_unmute_round_trip(cli_env, monkeypatch, db_at_root):
    p = FakePendant()
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: p)
    assert "Pendant muted (NOT_RECORDING)" in cli_env.invoke(["mute"]).output
    assert db_at_root.get_status("muted_by_owner_since_ms")
    assert db_at_root.latest_device_status()[1] == "mute"
    db_at_root.set_status("unmute_pending_since_ms", "5")
    db_at_root.set_status("muted_by_recorder_since_ms", "5")
    out = cli_env.invoke(["unmute"]).output
    assert "LISTENING" in out and p.log.count("start") == 1
    sessions = " ".join(p.log).split("exit")
    assert all(s.split()[1].startswith("set_time:") for s in sessions[:2])   # mute and unmute set the clock first
    assert db_at_root.latest_device_status()[1] == "unmute"
    for key in ("unmute_pending_since_ms", "muted_by_recorder_since_ms", "muted_by_owner_since_ms"):
        assert db_at_root.get_status(key) is None


def test_mute_not_confirmed_exits_1(cli_env, monkeypatch, db_at_root):
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant(stop_result="LISTENING"))
    r = cli_env.invoke(["mute"])
    assert r.exit_code == 1 and "Mute not confirmed: LISTENING" in r.output
    assert db_at_root.get_status("muted_by_owner_since_ms") is None


def test_unmute_failure_exits_1(cli_env, monkeypatch):
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant(state="NOT_RECORDING", start_result="NOT_RECORDING"))
    r = cli_env.invoke(["unmute"])
    assert r.exit_code == 1 and "still NOT_RECORDING" in r.output


def test_device_error_is_reported_once_without_retry(cli_env, monkeypatch):
    p = FakePendant(fail_on={"stop": DeviceError("timeout")})
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: p)
    r = cli_env.invoke(["mute"])
    assert r.exit_code == 1 and "timeout" in r.output and p.log.count("stop") == 1


def test_status_shows_pending_unmute(cli_env, db_at_root):
    db_at_root.set_status("unmute_pending_since_ms", "1792821367981")
    out = cli_env.invoke(["status"]).output
    assert "Pendant muted by the recorder, unmute pending since " + _T in out
    assert "run 'lavalier unmute' or hold the button" in out


def test_status_shows_the_last_sync(cli_env, monkeypatch):
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant(pages=(0, 9)))
    cli_env.invoke(["sync"])
    out = cli_env.invoke(["status"]).output
    assert "skipped (nothing to do)" in out and "Last sync: " in out and "(sync)" in out


def test_owner_mute_clears_the_recorder_markers(cli_env, monkeypatch, db_at_root):
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant())
    db_at_root.set_status("unmute_pending_since_ms", "5")
    db_at_root.set_status("muted_by_recorder_since_ms", "5")
    assert cli_env.invoke(["mute"]).exit_code == 0
    assert db_at_root.get_status("muted_by_owner_since_ms")
    assert db_at_root.get_status("unmute_pending_since_ms") is None
    assert db_at_root.get_status("muted_by_recorder_since_ms") is None


# --- final review fixes: who muted the pendant (C1, I2) ---

def _record(db, state, *, partial=False):
    from lavalier.models import DeviceSnapshot
    db.record_device_status(DeviceSnapshot(1792821367981, not partial, state, 0, 9, 90, -10, "USB_DISCONNECTED", "1.1.3", 7),
                            source="sync", charger_signal="none")


def test_status_shows_a_recorder_mute_marker(cli_env, db_at_root):
    db_at_root.set_status("muted_by_recorder_since_ms", "1792821367981")
    out = cli_env.invoke(["status"]).output
    assert "Pendant muted by the recorder since " + _T in out and "unmute pending" not in out


def test_status_prefers_the_pending_line_when_both_recorder_keys_are_set(cli_env, db_at_root):
    db_at_root.set_status("muted_by_recorder_since_ms", "1792821367981")
    db_at_root.set_status("unmute_pending_since_ms", "1792821367981")
    out = cli_env.invoke(["status"]).output
    assert out.count("Pendant muted by the recorder") == 1 and "unmute pending since " + _T in out


def test_status_says_muted_by_you(cli_env, db_at_root):
    db_at_root.set_status("muted_by_owner_since_ms", "1792821367981")
    _record(db_at_root, "NOT_RECORDING")
    assert "Pendant muted by you since " + _T in cli_env.invoke(["status"]).output


@pytest.mark.parametrize("state,partial", [("LISTENING", False), ("NOT_RECORDING", True)])
def test_status_does_not_say_muted_by_you_unless_the_last_full_read_is_not_recording(cli_env, db_at_root, state, partial):
    db_at_root.set_status("muted_by_owner_since_ms", "1792821367981")
    _record(db_at_root, state, partial=partial)
    assert "muted by you" not in cli_env.invoke(["status"]).output


def test_mute_clears_recorder_keys_before_the_read_back(cli_env, db_at_root, monkeypatch):
    db_at_root.set_status("unmute_pending_since_ms", "1000"); db_at_root.set_status("muted_by_recorder_since_ms", "900")
    p = FakePendant(stop_result="NOT_RECORDING", fail_on={"status": DeviceError("timeout")})   # stop lands, read fails
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: p)
    cli_env.invoke(["mute"])
    assert db_at_root.get_status("unmute_pending_since_ms") is None and db_at_root.get_status("muted_by_recorder_since_ms") is None


def test_cli_quiets_the_fork_connection_log(cli_env):
    for n in ("ble", "session"):
        logging.getLogger(f"pendant_client.{n}").setLevel(logging.NOTSET)
    cli_env.invoke(["status"])
    assert logging.getLogger("pendant_client.ble").level == logging.ERROR
    assert logging.getLogger("pendant_client.session").level == logging.ERROR
    assert logging.getLogger("pendant_client.decode").getEffectiveLevel() <= logging.WARNING


def test_quiet_fork_chatter_leaves_decode_warnings_audible():
    from lavalier.logsetup import quiet_fork_chatter
    quiet_fork_chatter()
    assert logging.getLogger("pendant_client.ble").level == logging.ERROR
    assert logging.getLogger("pendant_client.session").level == logging.ERROR
    assert logging.getLogger("pendant_client.decode").getEffectiveLevel() <= logging.WARNING


async def test_owner_mute_with_a_failed_read_back_is_not_restored_by_the_next_poll(cli_env, db_at_root, monkeypatch):
    from lavalier.lock import SyncLock
    from lavalier.sync import run_sync
    from lavalier.config import Config
    from lavalier import actions
    cfg = Config(pendant_address="FAKE")
    lock = SyncLock(cli_env.root.root / ".lock", list_processes=lambda: [])
    p = FakePendant(fail_on={"status": DeviceError("timeout")})
    r = await actions.mute(db_at_root, cfg, lambda c: p, lock=lock, cdc_present=lambda: False, now_ms=lambda: 1_000_000)
    assert r["ok"] is False
    assert all(db_at_root.get_status(k) is None for k in
               ("unmute_pending_since_ms", "muted_by_recorder_since_ms", "muted_by_owner_since_ms"))
    q = FakePendant(state="NOT_RECORDING", pages=(0, 999))   # enough pages to drain
    rep = await run_sync(db_at_root, cli_env.root, cfg, q, now_ms=lambda: 1_100_000, lock=lock,
                         cdc_present=lambda: False, settle_s=0, scheduled=True)
    assert "start" not in q.log and rep.muted_by == "owner" and rep.unmute == "owner-mute-left"


def test_status_prints_only_the_recorder_line_when_both_markers_are_set(cli_env, db_at_root):
    db_at_root.set_status("muted_by_recorder_since_ms", "1792821367981")
    db_at_root.set_status("muted_by_owner_since_ms", "1792821367981")
    r = cli_env.invoke(["status"])
    assert "muted by the recorder" in r.output and "muted by you" not in r.output
