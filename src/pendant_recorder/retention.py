"""Audio retention rules."""

from typing import Optional

from pendant_recorder.config import Config
from pendant_recorder.models import ClipRecord

_DAY_MS = 86_400_000


def deadline_ms(clip: ClipRecord, cfg: Config, *, protected: bool) -> Optional[int]:
    """When the clip's audio may be deleted; None if it is never deleted (yet)."""
    if protected or clip.classification == "failed" or clip.transcribed_at is None:
        return None
    return clip.transcribed_at + cfg.retention_days * _DAY_MS
