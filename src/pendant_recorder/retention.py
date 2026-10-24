"""Audio retention rules."""

from typing import Optional

from pendant_recorder.config import Config
from pendant_recorder.db import Database
from pendant_recorder.models import ClipRecord
from pendant_recorder.paths import Paths

_DAY_MS = 86_400_000


def deadline_ms(clip: ClipRecord, cfg: Config, *, protected: bool) -> Optional[int]:
    """When the clip's audio may be deleted; None if it is never deleted (yet)."""
    if protected or clip.classification == "failed" or clip.transcribed_at is None:
        return None
    return clip.transcribed_at + cfg.retention_days * _DAY_MS


def _protected_clip_ids(db: Database, day) -> set[str]:
    """Clips in a starred or pinned conversation of the day."""
    ids: set[str] = set()
    for conv in db.conversations_for_day(day):
        if conv.star_ms or conv.pinned:
            ids.update(conv.clip_ids)
    return ids


def sweep(db: Database, paths: Paths, cfg: Config, *, now_ms: int) -> tuple[int, int]:
    """Delete expired clip audio and old capture files; returns (clips, captures) deleted."""
    protected_by_day: dict = {}
    clips_deleted = 0
    for clip in db.clips_with_audio_older_than(now_ms):
        if clip.day not in protected_by_day:
            protected_by_day[clip.day] = _protected_clip_ids(db, clip.day)
        protected = clip.clip_id in protected_by_day[clip.day]
        deadline = deadline_ms(clip, cfg, protected=protected)
        if deadline is None or deadline > now_ms:
            continue
        (paths.root / clip.path).unlink(missing_ok=True)
        with db.transaction():
            db.clear_clip_path(clip.clip_id)
            db.mark_day_dirty(clip.day)
        clips_deleted += 1

    captures_deleted = 0
    for capture_id, path in db.captures_decoded_before(now_ms - cfg.retention_days * _DAY_MS):
        if db.clips_with_audio_for_capture(capture_id) > 0:
            continue
        file = paths.root / path  # captures are stored by absolute path; joining keeps it as is
        if not file.exists():
            continue
        file.unlink(missing_ok=True)
        captures_deleted += 1
    return clips_deleted, captures_deleted
