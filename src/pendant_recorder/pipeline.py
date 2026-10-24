"""Chain the stages: loudness, transcription, day files, retention."""

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from pendant_recorder import noise
from pendant_recorder.audio import ffmpeg_available, measure_loudness
from pendant_recorder.clips import decode_new_pages
from pendant_recorder.config import Config
from pendant_recorder.dayfile import write_day
from pendant_recorder.db import Database
from pendant_recorder.group import press_times, rebuild_day
from pendant_recorder.models import ClipRecord
from pendant_recorder.pages import ImportResult, import_capture
from pendant_recorder.paths import Paths
from pendant_recorder.retention import deadline_ms, sweep
from pendant_recorder.transcribe import Transcriber, transcribe_pending

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


def process(db: Database, paths: Paths, cfg: Config, transcriber: Transcriber, *, now_ms: int) -> ProcessReport:
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

    try:
        dirty = db.days_dirty()
    except Exception:
        log.exception("stage day files failed: cannot list dirty days")
        dirty = []
    for day in dirty:
        try:
            rebuild_day(db, day, cfg)
            if not db.clips_for_day(day) and not press_times(db, day):
                db.mark_day_clean(day)  # only status events: nothing worth a file
                continue
            write_day(db, paths, day, cfg, now_ms=now_ms)
            report.days_written.append(day)
        except Exception:
            log.exception("stage day files failed for %s", day)
    report.days_written.sort()

    try:
        report.clips_deleted, report.captures_deleted = sweep(db, paths, cfg, now_ms=now_ms)
    except Exception:
        log.exception("stage retention failed")
    return report


def retry_failed(db: Database) -> int:
    """Put every failed clip back in the queue; the next process retries it."""
    with db.transaction():
        return db.reset_failed_clips()


def import_and_decode(
    db: Database, paths: Paths, src: Path, *, complete: bool = True, capture_day: date,
) -> tuple[ImportResult, list[ClipRecord]]:
    """Import and decode in one step. Re-importing a decoded capture adds nothing; re-importing
    one whose decode failed decodes it again."""
    imp = import_capture(db, paths, src, complete=complete)
    clips = decode_new_pages(db, paths, imp, capture_day=capture_day)
    db.set_status("last_import_iso", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return imp, clips


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
        for d in [deadline_ms(c, cfg, protected=c.clip_id in protected)] if d is not None
    ]
    next_deletion = datetime.fromtimestamp(min(deadlines) / 1000).date().isoformat() if deadlines else None
    last_process = db.get_status("last_process")
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
    }
