"""The sync engine: connect, set the clock, read status, decide, mute, drain, restore.

Policy lives here; `device.py` only carries commands. Every device command is sent once:
a failure is reported, never retried, and a second command is only sent after a status read.
"""

import asyncio
import contextlib
import dataclasses
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from lavalier.capture import CaptureFile, CaptureSink
from lavalier.charger import ChargerDecision, charger_decision
from lavalier.config import Config
from lavalier.db import Database
from lavalier.device import DeviceError, LinkDropped, Pendant, PendantNotInRange
from lavalier.lock import LockHeld, SyncLock
from lavalier.models import DeviceSnapshot
from lavalier.paths import Paths
from lavalier.pipeline import ProcessReport, import_and_decode, process
from lavalier.transcribe import Transcriber

UNMUTE_PENDING_MAX_MS = 30 * 60 * 1000
HEARTBEAT_EVERY = 100

# status keys
QUIET_POLLS = "quiet_polls"
LAST_SEEN = "last_seen_ms"
LAST_FIRMWARE = "last_firmware_ver"
MUTED_SINCE = "muted_by_recorder_since_ms"
UNMUTE_PENDING = "unmute_pending_since_ms"

_log = logging.getLogger("lavalier.sync")


@dataclass
class SyncReport:
    outcome: str          # "not-in-range" | "locked" | "refused" | "skipped" | "dry-run" | "drained" | "error"
    reason: str
    pages: int = 0
    messages: int = 0
    capture: Optional[Path] = None
    capture_complete: bool = True
    muted_by: Optional[str] = None      # None | "recorder" | "owner"
    unmute: str = "n/a"                 # "n/a" | "confirmed" | "confirmed-recording" | "pending" | "owner-mute-left" | "retried"
    status: Optional[DeviceSnapshot] = None
    charger_signal: str = "none"
    error: Optional[str] = None

    def to_json_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["capture"] = str(self.capture) if self.capture is not None else None
        return d


def decide_drain(snap: DeviceSnapshot, charger: ChargerDecision, last_drain_ok_ms: Optional[int], *,
                 now_ms: int, cfg: Config) -> tuple[bool, str]:
    if charger.on_charger:
        return True, f"on charger ({charger.signal})"
    if snap.pages_waiting >= cfg.drain_pages_threshold:
        return True, f"pages waiting {snap.pages_waiting} >= {cfg.drain_pages_threshold}"
    if last_drain_ok_ms is not None and now_ms - last_drain_ok_ms > cfg.drain_after_hours * 3_600_000:
        return True, f"last drain {(now_ms - last_drain_ok_ms) // 3_600_000}h ago"
    return False, "nothing to do"


def _int_status(db: Database, key: str) -> Optional[int]:
    v = db.get_status(key)
    return int(v) if v else None


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _state(snap: DeviceSnapshot) -> str:
    """The recording state, or "partial status": a partial read decodes as NOT_RECORDING and proves nothing."""
    return snap.recording_state if snap.has_all_fields else "partial status"


def _local_day(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000).date()


class _Refused(Exception):
    pass


class _Run:
    """One sync: the report being built plus the context every step needs."""

    def __init__(self, db, paths, cfg, pendant, now_ms, lock, cdc_present, settle_s, log):
        self.db, self.paths, self.cfg, self.pendant = db, paths, cfg, pendant
        self.now_ms, self.lock, self.cdc_present, self.settle_s, self.log = now_ms, lock, cdc_present, settle_s, log
        self.report = SyncReport(outcome="error", reason="")
        self.capture_id: Optional[int] = None
        self.suffixes: list[str] = []
        self.link_gone = False

    async def read_status(self) -> DeviceSnapshot:
        """status(), filled with the firmware and storage instance from the poll, and recorded."""
        snap = await self.pendant.status()
        if self.report.status is not None:
            snap = dataclasses.replace(snap, firmware_ver=self.report.status.firmware_ver,
                                       storage_instance=self.report.status.storage_instance)
        self.record(snap)
        return snap

    def record(self, snap: DeviceSnapshot) -> None:
        self.db.record_device_status(snap, source="sync", charger_signal=self.report.charger_signal)
        self.report.status = snap

    # step 3
    async def poll(self) -> ChargerDecision:
        await self.pendant.set_time(self.now_ms())
        firmware, storage_instance = await self.pendant.info()
        snap = dataclasses.replace(await self.pendant.status(), firmware_ver=firmware,
                                   storage_instance=storage_instance)
        quiet = (_int_status(self.db, QUIET_POLLS) or 0) + 1 if (
            snap.has_all_fields and snap.recording_state == "LISTENING") else 0
        self.db.set_status(QUIET_POLLS, str(quiet))
        charger = charger_decision(snap, cdc=self.cdc_present(), quiet_polls=quiet)
        self.report.charger_signal = charger.signal
        self.record(snap)
        self.db.set_status(LAST_SEEN, str(self.now_ms()))
        if _state(snap) in ("LISTENING", "RECORDING"):
            # the pendant is not muted, whoever unmuted it: no mute marker can still be true
            if self.db.get_status(UNMUTE_PENDING):
                self.log.info("unmute pending cleared: pendant is %s", snap.recording_state)
            self.clear_mute_keys()
        self.check_firmware(firmware)
        return charger

    def clear_mute_keys(self) -> None:
        self.db.clear_status(UNMUTE_PENDING)
        self.db.clear_status(MUTED_SINCE)

    def add_error(self, message: str) -> None:
        self.report.outcome = "error"
        self.report.error = message if self.report.error is None else f"{self.report.error}; {message}"

    def check_firmware(self, firmware: str) -> None:
        last = self.db.get_status(LAST_FIRMWARE)
        if last and firmware != last:
            self.log.warning("firmware changed %s -> %s", last, firmware)
        if firmware:
            self.db.set_status(LAST_FIRMWARE, firmware)
        required = self.cfg.require_firmware
        if required and firmware != required:
            raise _Refused(f"firmware {firmware} != required {required}")

    # step 4
    async def retry_pending_unmute(self) -> None:
        since = _int_status(self.db, UNMUTE_PENDING)
        snap = self.report.status
        if since is None or not snap.has_all_fields:
            return
        if self.now_ms() - since >= UNMUTE_PENDING_MAX_MS:
            self.suffixes.append(f"unmute pending since {_iso(since)}")
            return
        if snap.recording_state != "NOT_RECORDING":
            return
        await self.pendant.start_recording()
        await asyncio.sleep(self.settle_s)
        state = _state(await self.read_status())
        if state in ("LISTENING", "RECORDING"):
            self.clear_mute_keys()
            self.report.unmute = "retried"
            self.log.info("pending unmute retried: %s", state)
        else:
            self.log.warning("pending unmute retried, still %s", state)

    # step 7: returns False when the mute was not confirmed and nothing may be drained
    async def mute(self) -> bool:
        snap = self.report.status
        if not snap.has_all_fields:
            self.suffixes.append("partial status, no mute")
            return True
        if snap.recording_state == "NOT_RECORDING":
            self.report.muted_by = "owner"
            return True
        # mark the mute before sending it, so a stop that lands and then fails is never taken for the owner's
        self.db.set_status(MUTED_SINCE, str(self.now_ms()))
        self.report.muted_by = "recorder"
        try:
            await self.pendant.stop_recording()
            state = _state(await self.read_status())
        except LinkDropped as e:
            self.link_gone = True
            self.add_error(str(e))
            return False
        except DeviceError as e:
            self.add_error(str(e))
            return False
        if state == "NOT_RECORDING":
            return True
        self.add_error(f"mute not confirmed: {state}")
        if state in ("LISTENING", "RECORDING"):  # the stop did not take: nothing to restore
            self.report.muted_by = None
            self.db.clear_status(MUTED_SINCE)
        return False

    # step 8: returns the capture file (or None) and the error that stopped the drain, if any
    async def drain(self) -> tuple[Optional[CaptureFile], Optional[str]]:
        sink = CaptureSink(self.paths, ble_identifier=self.cfg.pendant_address,
                           fsync_every=self.cfg.fsync_every_pages, started_ms=self.now_ms())
        complete, stopped_by = False, None
        try:
            n = 0
            async with contextlib.aclosing(self.pendant.drain(idle_s=self.cfg.drain_idle_timeout_s)) as stream:
                async for payload in stream:
                    sink.add(payload)
                    n += 1
                    if n % HEARTBEAT_EVERY == 0:
                        self.lock.heartbeat()
            complete = True
        except LinkDropped as e:
            self.log.warning("link dropped mid-drain: %s", e)
            self.link_gone = True
        except DeviceError as e:
            self.log.error("device error mid-drain: %s", e)
            stopped_by = str(e)
        except LockHeld as e:
            self.log.error("lock lost mid-drain: %s", e)
            stopped_by = str(e)
        except Exception as e:  # e.g. the disk filled: keep and import what is already written
            self.log.exception("capture write failed mid-drain")
            stopped_by = str(e)
        finally:
            cf, close_error = self._close_sink(sink, complete)
        if close_error is not None:
            stopped_by = close_error if stopped_by is None else f"{stopped_by}; {close_error}"
        self.report.capture_complete = complete
        return cf, stopped_by

    def _close_sink(self, sink: CaptureSink, complete: bool) -> tuple[Optional[CaptureFile], Optional[str]]:
        try:
            return sink.close(complete=complete), None
        except Exception as e:  # never let a failed close hide why the drain stopped
            self.log.exception("closing the capture %s failed", sink.path)
            return None, f"capture close failed: {e}"

    # step 9: the installed copy becomes canonical; the sink's file goes only once it is in
    def import_capture(self, cf: CaptureFile) -> None:
        self.report.capture = cf.path
        self.report.pages, self.report.messages = cf.pages, cf.messages
        imp, _ = import_and_decode(self.db, self.paths, cf.path, complete=cf.complete,
                                   capture_day=_local_day(self.now_ms()),
                                   storage_instance=self.report.status.storage_instance)
        self.capture_id = imp.capture_id
        installed = self.paths.root / imp.path
        if installed != cf.path:
            cf.path.unlink(missing_ok=True)
        self.report.capture = installed

    # step 10
    async def restore(self) -> None:
        if self.report.muted_by == "owner":
            self.report.unmute = "owner-mute-left"
            return
        if self.report.muted_by != "recorder":
            return
        if self.link_gone:
            state = "link gone"
        else:
            # mark the unmute pending before sending it: an exception nobody maps must not leave the
            # recorder's mute set without the flag that makes the next sync retry
            self.db.set_status(UNMUTE_PENDING, str(self.now_ms()))
            try:
                await self.pendant.start_recording()
                await asyncio.sleep(self.settle_s)
                state = _state(await self.read_status())
            except LinkDropped as e:
                self.link_gone = True
                state = f"link gone ({e})"
            except DeviceError as e:
                self.add_error(str(e))
                state = f"device error ({e})"
        if state == "LISTENING":
            self.report.unmute = "confirmed"
            self.clear_mute_keys()
        elif state == "RECORDING":
            self.report.unmute = "confirmed-recording"
            self.log.warning("forced recording after StartRecording")
            self.clear_mute_keys()
        else:
            self.report.unmute = "pending"
            self.db.set_status(UNMUTE_PENDING, str(self.now_ms()))
            self.log.error("unmute not confirmed: %s; will retry on the next sync", state)

    def finish(self, run_id: int) -> None:
        r = self.report
        if self.suffixes:
            r.reason = "; ".join([r.reason, *self.suffixes])
        self.db.finish_sync_run(
            run_id, ended_ms=self.now_ms(), outcome=r.outcome, reason=r.reason, pages=r.pages,
            messages=r.messages, capture_id=self.capture_id, muted_by=r.muted_by, unmute=r.unmute,
            error=r.error)


async def run_sync(db: Database, paths: Paths, cfg: Config, pendant: Pendant, *, now_ms: Callable[[], int],
                   lock: SyncLock, cdc_present: Callable[[], bool], dry_run: bool = False,
                   settle_s: float = 1.0, log: logging.Logger = _log) -> SyncReport:
    run = _Run(db, paths, cfg, pendant, now_ms, lock, cdc_present, settle_s, log)
    report = run.report
    run_id = db.start_sync_run(now_ms())
    try:
        # 1. one device user at a time
        try:
            lock.acquire()
        except LockHeld as e:
            report.outcome, report.reason = "locked", str(e)
            return report
        try:
            await _connected(run, dry_run)
        finally:
            lock.release()
    except Exception as e:  # 11. anything unexpected: report it, never retry
        log.exception("sync failed")
        report.outcome, report.error = "error", str(e)
    finally:
        run.finish(run_id)
    return report


async def _connected(run: _Run, dry_run: bool) -> None:
    report, db = run.report, run.db
    async with contextlib.AsyncExitStack() as stack:
        # 2. connect; the exit stack closes the session on every path below
        try:
            await stack.enter_async_context(run.pendant)
        except PendantNotInRange:
            db.set_status(QUIET_POLLS, "0")
            report.outcome, report.reason = "not-in-range", "not advertising"
            return
        # 3. clock, info, status, firmware
        try:
            charger = await run.poll()
        except _Refused as e:
            report.outcome, report.reason = "refused", str(e)
            return
        # 4. a pending unmute from an earlier sync
        if not dry_run:
            await run.retry_pending_unmute()
        # 5. decide
        drain, reason = decide_drain(report.status, charger, db.last_drain_ok_ms(), now_ms=run.now_ms(), cfg=run.cfg)
        report.reason = reason
        if not drain:
            report.outcome = "skipped"
            return
        db.set_status(QUIET_POLLS, "0")
        # 6. dry run stops here
        if dry_run:
            report.outcome, report.reason = "dry-run", f"would drain: {reason}"
            return
        # 7-10. mute, drain, import, restore
        await _mute_drain_restore(run)


async def _mute_drain_restore(run: _Run) -> None:
    report = run.report
    try:
        if not await run.mute():
            return
        cf, stopped_by = await run.drain()
        if cf is not None:
            try:
                run.import_capture(cf)
            except Exception as e:  # the sink's file stays on disk: nothing is lost
                run.log.exception("import of %s failed", cf.path)
                run.add_error(str(e))
                return
        if stopped_by is not None:
            run.add_error(stopped_by)
        elif cf is None and not report.capture_complete:
            run.add_error("link dropped before any message")
        else:
            report.outcome = "drained"
    finally:
        await run.restore()


def after_sync(db: Database, paths: Paths, cfg: Config, report: SyncReport, transcriber: Transcriber, *,
               now_ms: int) -> Optional[ProcessReport]:
    """Process what a sync brought in, whatever its outcome; no capture means nothing came in."""
    if report.capture is None:
        return None
    return process(db, paths, cfg, transcriber, now_ms=now_ms)
