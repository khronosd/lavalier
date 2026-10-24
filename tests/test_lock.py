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


def _lk(tmp_path, *, now=2000, alive=lambda p: True):
    return SyncLock(tmp_path / ".lock", now_ms=lambda: now, pid_alive=alive, list_processes=lambda: [])


def test_heartbeat_rewrites_timestamp_and_keeps_our_pid(tmp_path):
    clock = [5000]
    lk = SyncLock(tmp_path / ".lock", now_ms=lambda: clock[0], pid_alive=lambda p: True, list_processes=lambda: [])
    with lk:
        clock[0] = 9000
        lk.heartbeat()
        assert (tmp_path / ".lock").read_text() == f"{os.getpid()}\n9000\n"


def test_heartbeat_raises_when_the_lock_was_taken_by_another_pid(tmp_path):
    lk = _lk(tmp_path)
    lk.acquire()
    (tmp_path / ".lock").write_text("424242\n1500\n")
    with pytest.raises(LockHeld, match="lost: pid 424242"):
        lk.heartbeat()
    assert (tmp_path / ".lock").read_text() == "424242\n1500\n"


def test_heartbeat_raises_when_the_file_is_gone_or_malformed(tmp_path):
    lk = _lk(tmp_path)
    lk.acquire()
    (tmp_path / ".lock").unlink()
    with pytest.raises(LockHeld, match="lost"):
        lk.heartbeat()
    (tmp_path / ".lock").write_text("garbage\n")
    with pytest.raises(LockHeld, match="lost"):
        lk.heartbeat()


def test_release_leaves_a_foreign_lock_in_place(tmp_path):
    lk = _lk(tmp_path)
    lk.acquire()
    (tmp_path / ".lock").write_text("424242\n1500\n")
    lk.release()
    assert (tmp_path / ".lock").read_text() == "424242\n1500\n"


def test_release_when_the_file_is_already_gone_does_not_raise(tmp_path):
    _lk(tmp_path).release()


def test_malformed_lock_file_is_broken_and_taken(tmp_path):
    (tmp_path / ".lock").write_text("garbage\n")
    lk = _lk(tmp_path)
    lk.acquire()
    assert (tmp_path / ".lock").read_text() == f"{os.getpid()}\n2000\n"


def test_stale_boundary_is_exact(tmp_path):
    (tmp_path / ".lock").write_text("424242\n1000\n")
    with pytest.raises(LockHeld, match="pid 424242"):
        _lk(tmp_path, now=1000 + STALE_AFTER_MS - 1).acquire()
    lk = _lk(tmp_path, now=1000 + STALE_AFTER_MS)
    lk.acquire()
    assert (tmp_path / ".lock").read_text() == f"{os.getpid()}\n{1000 + STALE_AFTER_MS}\n"


def test_stale_break_leaves_our_pid_and_clock(tmp_path):
    (tmp_path / ".lock").write_text("424242\n1000\n")
    _lk(tmp_path, alive=lambda p: False).acquire()
    assert (tmp_path / ".lock").read_text() == f"{os.getpid()}\n2000\n"
    (tmp_path / ".lock").write_text("424242\n1000\n")
    _lk(tmp_path, now=1000 + STALE_AFTER_MS + 1).acquire()
    assert (tmp_path / ".lock").read_text() == f"{os.getpid()}\n{1000 + STALE_AFTER_MS + 1}\n"


def test_exclusive_create_loses_the_race_to_a_live_foreign_lock(tmp_path, monkeypatch):
    real_link = os.link
    calls = []

    def racing_link(src, dst, *a, **kw):
        if not calls:
            calls.append(1)
            (tmp_path / ".lock").write_text("424242\n1900\n")
        return real_link(src, dst, *a, **kw)

    monkeypatch.setattr(os, "link", racing_link)
    with pytest.raises(LockHeld, match="pid 424242"):
        _lk(tmp_path, alive=lambda p: p == 424242).acquire()
    assert (tmp_path / ".lock").read_text() == "424242\n1900\n"
    assert [p.name for p in tmp_path.iterdir()] == [".lock"]
