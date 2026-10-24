"""Device actions shared by the headless CLI and the app process.

Each returns a JSON-able dict: the CLI prints it and picks the exit code, the app hands it to
the control server. Every device command is sent once; a failure is reported, never retried.
"""

import asyncio
import dataclasses
import json
from typing import Awaitable, Callable, Optional

from lavalier.charger import charger_decision
from lavalier.config import Config
from lavalier.db import Database
from lavalier.device import BlePendant, DeviceError, Pendant, PendantNotInRange
from lavalier.lock import LockHeld, SyncLock
from lavalier.models import DeviceSnapshot
from lavalier.paths import Paths
from lavalier.pipeline import ProcessReport, status_summary
from lavalier.probe import read_status
from lavalier.sync import MUTED_SINCE, UNMUTE_PENDING, SyncReport, after_sync, brought_audio
from lavalier.transcribe import Transcriber

ADDRESS_MISSING = "set pendant_address in config.toml"
OWNER_MUTE = "muted_by_owner_since_ms"

PendantFactory = Callable[[Config], Pendant]


def ble_pendant(cfg: Config) -> Pendant:
    return BlePendant(cfg.pendant_address, scan_timeout_s=cfg.scan_timeout_s)


def another_process(holder: object) -> str:
    return f"Another process is using the pendant: {holder}"


def state_of(snap: DeviceSnapshot) -> str:
    """The recording state, or "partial status": a partial read decodes as NOT_RECORDING and proves nothing."""
    return snap.recording_state if snap.has_all_fields else "partial status"


async def _send_and_reread(pendant: Pendant, send: str, settle_s: float, now_ms: Callable[[], int],
                           after_send: Callable[[], None] = lambda: None) -> DeviceSnapshot:
    """A mutating session: the clock is set first, as on every sync (the pendant does not record
    without a time sync, and its clock does not survive a flat battery)."""
    async with pendant as p:
        await p.set_time(now_ms())
        firmware_ver, storage_instance = await p.info()
        await getattr(p, send)()
        after_send()  # the command has landed: bookkeeping that must survive a failed read-back
        await asyncio.sleep(settle_s)
        snap = await p.status()
    return dataclasses.replace(snap, read_at_ms=now_ms(), firmware_ver=firmware_ver,
                               storage_instance=storage_instance)


async def _session(db: Database, cfg: Config, pendant_factory: PendantFactory, *, lock: SyncLock,
                   cdc_present: Callable[[], bool], source: str,
                   op: Callable[[Pendant], Awaitable[DeviceSnapshot]]) -> tuple[Optional[DeviceSnapshot], Optional[str]]:
    """One device session under the file lock; the snapshot it ends with is recorded. (snap, error)."""
    if not cfg.pendant_address:
        return None, ADDRESS_MISSING
    try:
        lock.acquire()
    except LockHeld as e:
        return None, another_process(e)
    try:
        snap = await op(pendant_factory(cfg))
    except PendantNotInRange:
        return None, "Pendant not in range"
    except DeviceError as e:
        return None, f"Device error: {e}"
    finally:
        lock.release()
    signal = charger_decision(snap, cdc=cdc_present(), quiet_polls=0).signal
    db.record_device_status(snap, source=source, charger_signal=signal)
    return snap, None


async def mute(db: Database, cfg: Config, pendant_factory: PendantFactory, *, lock: SyncLock,
               cdc_present: Callable[[], bool], now_ms: Callable[[], int]) -> dict:
    """The owner's mute. Once confirmed, no recorder mute marker survives it, so a pending
    recorder unmute can never be retried over the owner's mute."""
    def stop_landed() -> None:
        # the stop was sent: whatever happens to the read-back, the recorder's mute is over (the pendant
        # is stopped, and by us on the owner's behalf), so no pending recorder unmute may restart it
        with db.transaction():
            db.clear_status(UNMUTE_PENDING)
            db.clear_status(MUTED_SINCE)

    snap, err = await _session(db, cfg, pendant_factory, lock=lock, cdc_present=cdc_present, source="mute",
                               op=lambda p: _send_and_reread(p, "stop_recording", 0, now_ms, stop_landed))
    if err is not None:
        return {"ok": False, "state": None, "error": err}
    state = state_of(snap)
    if state != "NOT_RECORDING":
        return {"ok": False, "state": state, "error": f"Mute not confirmed: {state}"}
    with db.transaction():
        db.set_status(OWNER_MUTE, str(now_ms()))
    return {"ok": True, "state": state, "error": None}


async def unmute(db: Database, cfg: Config, pendant_factory: PendantFactory, *, lock: SyncLock,
                 cdc_present: Callable[[], bool], now_ms: Callable[[], int], settle_s: float) -> dict:
    """Start recording again and, once confirmed, clear every mute marker."""
    snap, err = await _session(db, cfg, pendant_factory, lock=lock, cdc_present=cdc_present, source="unmute",
                               op=lambda p: _send_and_reread(p, "start_recording", settle_s, now_ms))
    if err is not None:
        return {"ok": False, "state": None, "error": err}
    state = state_of(snap)
    if state not in ("LISTENING", "RECORDING"):
        still = f"still {state}" if state == "NOT_RECORDING" else state
        return {"ok": False, "state": state, "error": f"Unmute not confirmed: {still}"}
    with db.transaction():
        for key in (UNMUTE_PENDING, MUTED_SINCE, OWNER_MUTE):
            db.clear_status(key)
    return {"ok": True, "state": state, "error": None}


async def status_live(db: Database, paths: Paths, cfg: Config, pendant_factory: PendantFactory, *, lock: SyncLock,
                      cdc_present: Callable[[], bool], now_ms: Callable[[], int]) -> dict:
    """A read-only status read (the clock is not set), then the summary, whether or not the read worked."""
    _, err = await _session(db, cfg, pendant_factory, lock=lock, cdc_present=cdc_present, source="live",
                            op=lambda p: read_status(p, now_ms=now_ms()))
    return {"ok": err is None, "error": err, "summary": status_summary(db, paths, cfg, now_ms=now_ms())}


def process_after_sync(db: Database, paths: Paths, cfg: Config, report: SyncReport,
                       make_transcriber: Callable[[], Transcriber], *, now_ms: int) -> Optional[ProcessReport]:
    """Process what a sync brought in (any outcome) and record it as the last process."""
    if not brought_audio(report):
        return None
    processed = after_sync(db, paths, cfg, report, make_transcriber(), now_ms=now_ms)
    if processed is not None:
        # the time makes every run's record distinct: the window refetches its data when it changes
        db.set_status("last_process", json.dumps({**processed.to_json_dict(), "processed_ms": now_ms}))
    return processed


def sync_result(report: SyncReport, processed: Optional[ProcessReport]) -> dict:
    return {"sync": report.to_json_dict(), "process": processed.to_json_dict() if processed is not None else None}
