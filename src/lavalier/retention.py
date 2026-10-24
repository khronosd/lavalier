"""Audio retention rules."""

import logging
from pathlib import Path
from typing import Optional

from lavalier.config import Config
from lavalier.db import Database
from lavalier.models import ClipRecord
from lavalier.paths import Paths
from lavalier.playback import evict, sweep_cache

log = logging.getLogger(__name__)

_DAY_MS = 86_400_000


def _inside_root(paths: Paths, file: Path) -> bool:
    """Retention only ever deletes under the state root, whatever a row says."""
    if file.resolve().is_relative_to(paths.root.resolve()):
        return True
    log.warning("refusing to delete %s: outside the state root %s", file, paths.root)
    return False


def deadline_ms(clip: ClipRecord, cfg: Config, *, protected: bool) -> Optional[int]:
    """When the clip's audio may be deleted; None if it is never deleted (yet)."""
    if protected or clip.classification == "failed" or clip.transcribed_at is None:
        return None
    return clip.transcribed_at + cfg.retention_days * _DAY_MS


def audio_expired(db: Database, clip: ClipRecord, cfg: Config, *, now_ms: int) -> bool:
    """Past its deadline, whether or not a sweep has deleted the file yet: the window never plays it."""
    deadline = deadline_ms(clip, cfg, protected=clip.clip_id in _protected_clip_ids(db, clip.day))
    return deadline is not None and deadline <= now_ms


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
        file = paths.root / clip.path
        if not _inside_root(paths, file):
            continue
        file.unlink(missing_ok=True)
        try:
            evict(paths, clip.clip_id)
        except OSError as e:  # must not stop the sweep; sweep_cache below removes it once it can
            log.warning("could not evict the cached AAC of %s: %s", clip.clip_id, e)
        with db.transaction():
            db.clear_clip_path(clip.clip_id)
            db.mark_day_dirty(clip.day)
        clips_deleted += 1

    captures_deleted = 0
    for capture_id, path in db.captures_decoded_before(now_ms - cfg.retention_days * _DAY_MS):
        if db.clips_with_audio_for_capture(capture_id) > 0:
            continue
        file = paths.root / path  # relative to the state root; an older absolute row joins as is
        if not file.exists() or not _inside_root(paths, file):
            continue
        file.unlink(missing_ok=True)
        captures_deleted += 1

    stale = sweep_cache(db, paths)
    if stale:
        log.info("removed %d cached AAC file(s) whose audio is gone", stale)
    return clips_deleted, captures_deleted
