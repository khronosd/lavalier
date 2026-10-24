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
        if pid != own_pid and "lavalier" not in cmd and OTHER_DEVICE_PROCESS.search(cmd)
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
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(f"{os.getpid()}\n{self._now_ms()}\n")
        os.replace(tmp, self.path)

    def acquire(self) -> None:
        others = other_device_processes(self._list_processes)
        if others:
            raise LockHeld(f"process: {others[0]}")
        if self.path.exists():
            held = self._read()
            if held is not None:
                pid, beat = held
                if self._pid_alive(pid) and self._now_ms() - beat < STALE_AFTER_MS:
                    raise LockHeld(f"pid {pid}")
        self._write()

    def heartbeat(self) -> None:
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
