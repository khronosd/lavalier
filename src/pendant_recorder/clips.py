"""Decode newly imported pages into dated Ogg Opus clips and events."""

import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from pendant_client.decode import decode_messages

from pendant_recorder.db import Database
from pendant_recorder.models import ClipRecord, EventRecord
from pendant_recorder.pages import ImportResult
from pendant_recorder.paths import Paths

# 2025-01-01T00:00:00Z: earlier timestamps mean the pendant clock was not set.
_MIN_VALID_MS = 1735689600000


def clip_id_for(first_absolute_ms: int) -> str:
    t = datetime.fromtimestamp(first_absolute_ms / 1000, tz=timezone.utc)
    return f"clip_{t:%Y%m%dT%H%M%S}.{first_absolute_ms % 1000:03d}Z"


def day_for(ms: int, *, fallback: date) -> tuple[date, bool]:
    if ms < _MIN_VALID_MS:
        return fallback, True
    return datetime.fromtimestamp(ms / 1000).date(), False


def decode_new_pages(db: Database, paths: Paths, imp: ImportResult, *, capture_day: date) -> list[ClipRecord]:
    if not imp.new_payloads:
        db.mark_capture_decoded(imp.capture_id)
        return []
    clips: list[ClipRecord] = []
    moves: list[tuple[Path, Path]] = []
    with tempfile.TemporaryDirectory() as tmp:
        with db.transaction():
            result = decode_messages(imp.new_payloads, Path(tmp) / "cap.opus")
            dirty: set[date] = set()
            for rec in result.recordings:
                assert rec.first_page_index is not None and rec.last_page_index is not None
                first_ms = rec.first_absolute_timestamp_ms
                clip_id = clip_id_for(first_ms)
                day, suspect = day_for(first_ms, fallback=capture_day)
                dest = paths.audio / day.isoformat() / f"{clip_id}.opus"
                moves.append((rec.path, dest))
                clip = ClipRecord(
                    clip_id=clip_id,
                    path=str(dest.relative_to(paths.root)),
                    day=day,
                    first_ms=first_ms,
                    last_ms=rec.last_absolute_timestamp_ms,
                    chunk_count=rec.chunk_count,
                    first_page=rec.first_page_index,
                    last_page=rec.last_page_index,
                    run=rec.runs[0],  # one run per capture in practice; take the first
                    capture_id=imp.capture_id,
                    opened_with_start_marker=rec.opened_with_start_marker,
                    closed_with_stop_marker=rec.closed_with_stop_marker,
                    clock_suspect=suspect,
                )
                db.add_clip(clip)
                clips.append(clip)
                dirty.add(day)
            for d in result.events:
                if d["type"] == "raw_status":
                    continue
                db.add_event(EventRecord(page_index=d["page_index"], absolute_ms=d["absolute_chunk_timestamp_ms"],
                                         type=d["type"], payload=d, capture_id=imp.capture_id))
                dirty.add(day_for(d["absolute_chunk_timestamp_ms"], fallback=capture_day)[0])
            for day in dirty:
                db.mark_day_dirty(day)
            db.mark_capture_decoded(imp.capture_id)
        # Rows are committed; only now move the files out of the temp dir.
        for src, dest in moves:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), dest)
    return clips
