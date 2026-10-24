"""One device user at a time: a lock file plus a check for other tools that talk to the pendant.

Lock file format (honoured by the lab's scripts too): line 1 the PID, line 2 the
last heartbeat in Unix milliseconds.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from lavalier.db import now_ms
from lavalier.vendor import is_vendor_app_command

STALE_AFTER_MS = 30 * 60 * 1000
OTHER_DEVICE_PROCESS = re.compile(r"(^|/)pendant(\s|$)|pendant_client|smpmgr|smp_probe")


class LockHeld(Exception):
    """Another device user is active; the message names it."""


def _ps_processes() -> list[tuple[int, str]]:
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True).stdout
    procs: list[tuple[int, str]] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            procs.append((int(parts[0]), parts[1]))
    return procs


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def other_device_processes(
    list_processes: Callable[[], list[tuple[int, str]]] = _ps_processes, *, own_pid: int = os.getpid()
) -> list[str]:
    return [
        cmd
        for pid, cmd in list_processes()
        if pid != own_pid and "lavalier" not in cmd
        and (OTHER_DEVICE_PROCESS.search(cmd) or is_vendor_app_command(cmd))
    ]


class SyncLock:
    def __init__(
        self,
        path: Path,
        *,
        now_ms: Callable[[], int] = now_ms,
        pid_alive: Callable[[int], bool] = _pid_alive,
        list_processes: Callable[[], list[tuple[int, str]]] = _ps_processes,
    ):
        self.path = Path(path)
        self._now_ms = now_ms
        self._pid_alive = pid_alive
        self._list_processes = list_processes

    def _read(self) -> tuple[int, int] | None:
        """(pid, heartbeat_ms) of the current lock file; None if absent or malformed."""
        try:
            lines = self.path.read_text().split()
            return int(lines[0]), int(lines[1])
        except (OSError, ValueError, IndexError):
            return None

    def _write(self) -> None:
        """Atomically replace the lock file with our PID and the current heartbeat."""
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(f"{os.getpid()}\n{self._now_ms()}\n")
        os.replace(tmp, self.path)

    def _create_exclusive(self) -> bool:
        """Take the lock only if no file exists; False if someone else's file is there."""
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.new")
        tmp.write_text(f"{os.getpid()}\n{self._now_ms()}\n")
        try:
            os.link(tmp, self.path)
            return True
        except FileExistsError:
            return False
        finally:
            tmp.unlink(missing_ok=True)

    def _is_live(self, held: tuple[int, int] | None) -> bool:
        return held is not None and self._pid_alive(held[0]) and self._now_ms() - held[1] < STALE_AFTER_MS

    # Known race (ruling R18): two processes judge the same lock stale, A renames it aside and
    # creates its own, then B renames A's fresh file aside believing it is the stale one and creates
    # its own; both now think they hold the lock. It needs two breakers of one dead or 30-minute-old
    # lock in the same instant. The overlap is bounded by `heartbeat`, which checks that the PID in
    # the file is still ours and raises LockHeld (ending A's drain) at its next heartbeat.
    def _break(self) -> None:
        """Move the stale file aside under a unique name, so only one breaker wins the rename."""
        aside = self.path.with_name(f"{self.path.name}.{os.getpid()}.stale")
        try:
            os.rename(self.path, aside)
        except FileNotFoundError:
            return
        aside.unlink(missing_ok=True)

    def acquire(self) -> None:
        others = other_device_processes(self._list_processes)
        if others:
            raise LockHeld(f"process: {others[0]}")
        for _ in range(2):
            if self._create_exclusive():
                return
            held = self._read()
            if self._is_live(held):
                raise LockHeld(f"pid {held[0]}")
            self._break()
        if self._create_exclusive():
            return
        held = self._read()
        raise LockHeld(f"pid {held[0]}" if held else "lock contended")

    def heartbeat(self) -> None:
        held = self._read()
        if held is None:
            raise LockHeld("lost")
        if held[0] != os.getpid():
            raise LockHeld(f"lost: pid {held[0]}")
        self._write()

    def release(self) -> None:
        held = self._read()
        if held is not None and held[0] == os.getpid():
            self.path.unlink(missing_ok=True)

    def __enter__(self) -> "SyncLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
