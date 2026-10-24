import os

import pytest

from lavalier.lock import STALE_AFTER_MS, LockHeld, SyncLock, other_device_processes


def test_acquire_writes_pid_and_heartbeat(tmp_path):
    lk = SyncLock(tmp_path / ".lock", now_ms=lambda: 5000, pid_alive=lambda p: True, list_processes=lambda: [])
    with lk:
        assert (tmp_path / ".lock").read_text() == f"{os.getpid()}\n5000\n"
    assert not (tmp_path / ".lock").exists()


def test_live_lock_from_another_pid_is_respected(tmp_path):
    (tmp_path / ".lock").write_text("424242\n1000\n")
    lk = SyncLock(tmp_path / ".lock", now_ms=lambda: 2000, pid_alive=lambda p: p == 424242, list_processes=lambda: [])
    with pytest.raises(LockHeld, match="pid 424242"):
        lk.acquire()


def test_stale_lock_is_broken(tmp_path):
    (tmp_path / ".lock").write_text("424242\n1000\n")
    dead = SyncLock(tmp_path / ".lock", now_ms=lambda: 2000, pid_alive=lambda p: False, list_processes=lambda: [])
    dead.acquire(); dead.release()
    (tmp_path / ".lock").write_text("424242\n1000\n")
    old = SyncLock(tmp_path / ".lock", now_ms=lambda: 1000 + STALE_AFTER_MS + 1, pid_alive=lambda p: True, list_processes=lambda: [])
    old.acquire(); old.release()


def test_other_device_processes_match_the_fork_and_lab_tools_but_not_us():
    procs = [(1, "/Users/k/Repos/pendant-cli/.venv/bin/python /Users/k/Repos/pendant-cli/.venv/bin/pendant status 501D"),
             (2, "/Users/k/.venvs/smpmgr/bin/smpmgr --ble 501D os echo"),
             (3, "/Users/k/Repos/lavalier/.venv/bin/python -m lavalier.app"),
             (4, "/Users/k/Repos/pendant-lab/.venv/bin/python scripts/smp_probe.py"),
             (5, "vim notes-about-pendants.md"),
             (os.getpid(), "pendant status")]
    found = other_device_processes(lambda: procs)
    assert [f.split()[-1] for f in found] == ["501D", "echo", "scripts/smp_probe.py"]


def test_acquire_refuses_while_the_fork_cli_runs(tmp_path):
    lk = SyncLock(tmp_path / ".lock", list_processes=lambda: [(9, "/x/.venv/bin/pendant sync 501D")])
    with pytest.raises(LockHeld, match="process:"):
        lk.acquire()
    assert not (tmp_path / ".lock").exists()
