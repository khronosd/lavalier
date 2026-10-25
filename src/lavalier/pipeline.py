"""Chain the stages: loudness, transcription, day files, retention."""

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from lavalier import noise
from lavalier.capture import SINK_NAME, open_sink_paths
from lavalier.audio import ffmpeg_available, measure_loudness
from lavalier.clips import decode_new_pages
from lavalier.config import Config
from lavalier.connectors.calendar import CalendarSource, label_day
from lavalier.dayfile import write_dirty_days
from lavalier.db import Database
from lavalier.group import rebuild_day
from lavalier.models import ClipRecord
from lavalier.pages import ImportResult, import_capture
from lavalier.paths import Paths
from lavalier.retention import deadline_ms, sweep
from lavalier.transcribe import Transcriber, transcribe_pending

log = logging.getLogger(__name__)


@dataclass
class ProcessReport:
    loudness_measured: int = 0
    transcribed: int = 0
    failed: int = 0
    days_written: list[date] = field(default_factory=list)
    clips_deleted: int = 0
    captures_deleted: int = 0

    def to_json_dict(self) -> dict:
        d = asdict(self)
        d["days_written"] = [x.isoformat() for x in self.days_written]
        return d


def process(db: Database, paths: Paths, cfg: Config, transcriber: Transcriber, *, now_ms: int,
            calendar: Optional[CalendarSource] = None) -> ProcessReport:
    report = ProcessReport()

    # Environment problems skip a stage and leave clips pending; they never mark clips failed.
    has_ffmpeg = ffmpeg_available()
    if not has_ffmpeg:
        log.warning("ffmpeg not found; skipping loudness and transcription, clips stay pending")
    else:
        try:
            report.loudness_measured = measure_loudness(db, paths)
        except Exception:
            log.exception("stage loudness failed")

    reason = transcriber.unavailable_reason()
    if reason is not None:
        log.warning("skipping transcription, clips stay pending: %s", reason)
    elif has_ffmpeg:
        try:
            report.transcribed, report.failed = transcribe_pending(
                db, paths, transcriber, lambda c, t: noise.classify(c, t, cfg))
        except Exception:
            log.exception("stage transcription failed")

    if calendar is not None and cfg.calendar_enabled:
        _label_dirty_days(db, cfg, calendar)

    report.days_written = write_dirty_days(db, paths, cfg, now_ms=now_ms)

    try:
        report.clips_deleted, report.captures_deleted = sweep(db, paths, cfg, now_ms=now_ms)
    except Exception:
        log.exception("stage retention failed")
    return report


def _label_dirty_days(db: Database, cfg: Config, calendar: CalendarSource) -> None:
    """Regroup each day this run will write, then label its conversations from the calendar. The
    regroup in write_dirty_days that follows keeps the labels (same id, same label)."""
    try:
        days = db.days_dirty()
    except Exception:
        log.exception("stage calendar labels failed: cannot list dirty days")
        return
    for day in days:
        try:
            rebuild_day(db, day, cfg)
            label_day(db, cfg, calendar, day)
        except Exception:
            log.exception("stage calendar labels failed for %s", day)


def retention_tick(db: Database, paths: Paths, cfg: Config, *, now_ms: int) -> ProcessReport:
    """Retention on its own, for the days no drain brings audio: sweep (which also clears stale cached
    AAC), then rewrite the day files whose audio changed, as process does."""
    report = ProcessReport()
    try:
        report.clips_deleted, report.captures_deleted = sweep(db, paths, cfg, now_ms=now_ms)
    except Exception:
        log.exception("stage retention failed")
    report.days_written = write_dirty_days(db, paths, cfg, now_ms=now_ms)
    return report


def retry_failed(db: Database) -> int:
    """Put every failed clip back in the queue; the next process retries it."""
    with db.transaction():
        return db.reset_failed_clips()


def import_and_decode(
    db: Database, paths: Paths, src: Path, *, complete: bool = True, capture_day: date,
    storage_instance: int = 0,
) -> tuple[ImportResult, list[ClipRecord]]:
    """Import and decode in one step. Re-importing a decoded capture adds nothing; re-importing
    one whose decode failed decodes it again."""
    imp = import_capture(db, paths, src, complete=complete, storage_instance=storage_instance)
    clips = decode_new_pages(db, paths, imp, capture_day=capture_day)
    db.set_status("last_import_iso", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return imp, clips


ORPHAN_MIN_AGE_S = 60


def sweep_orphan_captures(db: Database, paths: Paths, *, min_age_s: float = ORPHAN_MIN_AGE_S,
                          now_s=time.time) -> list[ImportResult]:
    """Import every sink file in captures/ that no captures row knows: what a drain wrote before it
    was cancelled, killed, or failed to close. The pendant already deleted those pages, so this is
    their only copy. Skips a sink this process still writes and any file modified within min_age_s
    (another process's live drain). Idempotent by sha: a sink left behind after its import committed
    is removed, its installed copy being canonical; when that capture's decode had failed, the
    installed copy is decoded again first and the sink is removed only once that succeeds."""
    latest = db.latest_device_status()
    storage_instance = latest[0].storage_instance if latest is not None else 0
    open_now = open_sink_paths()
    results: list[ImportResult] = []
    for f in sorted(paths.captures.glob("*.bin")) if paths.captures.exists() else []:
        if not SINK_NAME.match(f.name) or f in open_now:
            continue
        try:
            st = f.stat()
            if now_s() - st.st_mtime < min_age_s:
                continue
            known = db.capture_by_sha(hashlib.sha256(f.read_bytes()).hexdigest())
            if known is not None:
                installed = paths.root / db.capture_path(known)
                if installed == f:
                    continue
                if not db.capture_decoded(known):
                    # Its decode failed after the import committed: decode the installed copy
                    # again, and keep the sink until that succeeds.
                    imp, _ = import_and_decode(db, paths, installed, complete=False,
                                               capture_day=datetime.fromtimestamp(st.st_mtime).date(),
                                               storage_instance=storage_instance)
                    if not db.capture_decoded(known) and not imp.new_payloads and all(
                            db.page_owned_earlier(k, known) for k in db.pages_for_capture(known)):
                        # every page was handed to an earlier capture: nothing is left to decode
                        db.mark_capture_decoded(known)
                    if not db.capture_decoded(known):
                        log.warning("capture %s is still undecoded; sink %s left in place", known, f.name)
                        continue
                    log.warning("re-decoded undecoded capture %s from %s", known, installed.name)
                    results.append(imp)
                f.unlink(missing_ok=True)
                continue
            imp, _ = import_and_decode(db, paths, f, complete=False,
                                       capture_day=datetime.fromtimestamp(st.st_mtime).date(),
                                       storage_instance=storage_instance)
            if paths.root / imp.path != f:
                f.unlink(missing_ok=True)
            log.warning("imported orphan capture %s: %d new pages", f.name, imp.pages_new)
            results.append(imp)
        except Exception:
            log.exception("orphan capture %s could not be imported; left in place", f.name)
    return results


def import_and_process(
    db: Database, paths: Paths, cfg: Config, transcriber: Transcriber, src: Path,
    *, now_ms: int, capture_day: date, complete: bool = True,
) -> tuple[ImportResult, ProcessReport]:
    imp, _ = import_and_decode(db, paths, src, complete=complete, capture_day=capture_day)
    return imp, process(db, paths, cfg, transcriber, now_ms=now_ms)


def refresh_day(db: Database, day: date, cfg: Config) -> None:
    """Regroup the day if its grouping is stale, so a write never marks stale data clean."""
    if day in db.days_dirty():
        rebuild_day(db, day, cfg)


def _tree_bytes(root: Path) -> int:
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.exists() else 0


def status_summary(db: Database, paths: Paths, cfg: Config, *, now_ms: int) -> dict:
    days = db.days_with_clips()
    pending = len(db.clips_needing_transcript())
    protected: set[str] = set()
    pinned: list[str] = []
    long_presses = double_presses = 0
    for day in days:
        for conv in db.conversations_for_day(day):
            if conv.star_ms or conv.pinned:
                protected.update(conv.clip_ids)
            if conv.pinned:
                pinned.append(conv.conversation_id)
        for e in db.events_for_day(day, ["button"]):
            kind = e.payload.get("button_event")
            long_presses += kind == "BUTTON_LONG_PRESS"
            double_presses += kind == "BUTTON_DOUBLE_PRESS"
    deadlines = [
        d for day in days for c in db.clips_for_day(day) if c.path
        for d in [deadline_ms(c, cfg, protected=c.clip_id in protected)] if d is not None and d > now_ms
    ]  # a deadline already past is due at the next sweep, not a date to name
    next_deletion = datetime.fromtimestamp(min(deadlines) / 1000).date().isoformat() if deadlines else None
    last_process = db.get_status("last_process")
    latest = db.latest_device_status()
    device = None
    if latest is not None:
        snap, source, charger_signal = latest
        device = {**asdict(snap), "pages_waiting": snap.pages_waiting, "source": source,
                  "charger_signal": charger_signal, "age_s": max(0, (now_ms - snap.read_at_ms) // 1000)}
    last_sync = db.last_sync_run()
    insight_counts = db.insight_counts()
    def _ms(key: str):
        v = db.get_status(key)
        return int(v) if v else None
    return {
        "days_with_clips": [d.isoformat() for d in days],
        "pending_transcripts": pending,
        "failed_clips": db.count_failed_clips(),
        "audio_bytes": _tree_bytes(paths.audio),
        "capture_bytes": _tree_bytes(paths.captures),
        "next_deletion": next_deletion,
        "last_import": db.get_status("last_import_iso"),
        "pinned": pinned,
        "long_presses": long_presses,
        "double_presses": double_presses,
        "last_process": last_process,
        "device": device,
        "last_sync": asdict(last_sync) if last_sync is not None else None,
        "unmute_pending_since_ms": _ms("unmute_pending_since_ms"),
        "muted_by_recorder_since_ms": _ms("muted_by_recorder_since_ms"),
        "muted_by_owner_since_ms": _ms("muted_by_owner_since_ms"),
        "insights": {"days_done": insight_counts["done"], "days_error": insight_counts["error"]},
    }
