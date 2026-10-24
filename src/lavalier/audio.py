"""ffmpeg helpers: WAV conversion for the transcriber and loudness measurement."""
import logging
import re
import shutil
import subprocess
from pathlib import Path

from lavalier.db import Database
from lavalier.paths import Paths

log = logging.getLogger(__name__)

_MEAN = re.compile(r"mean_volume:\s*(-?[\d.]+|-?inf)\s*dB")
_MAX = re.compile(r"max_volume:\s*(-?[\d.]+|-?inf)\s*dB")


class AudioToolError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def to_wav16k(src: Path, dst: Path) -> None:
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise AudioToolError(f"ffmpeg failed ({r.returncode}) converting {src}: {r.stderr.strip()}")


def loudness(path: Path) -> tuple[float, float]:
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    mean, peak = _MEAN.search(r.stderr), _MAX.search(r.stderr)
    if r.returncode != 0 or not mean or not peak:
        raise AudioToolError(f"could not measure loudness of {path}: {r.stderr.strip()}")
    return float(mean.group(1)), float(peak.group(1))


def measure_loudness(db: Database, paths: Paths) -> int:
    count = 0
    for clip in db.clips_needing_loudness():
        f = paths.root / clip.path
        if not f.exists():
            log.warning("audio file missing for %s: %s", clip.clip_id, f)
            continue
        try:
            mean_db, peak_db = loudness(f)
        except FileNotFoundError as e:
            # the binary is missing: abort the stage, leave every clip pending
            raise AudioToolError("ffmpeg not found") from e
        except AudioToolError:
            log.exception("loudness failed for %s; marking it failed", clip.clip_id)
            with db.transaction():
                db.set_classification(clip.clip_id, "failed")
                db.mark_day_dirty(clip.day)
            continue
        db.set_loudness(clip.clip_id, mean_db, peak_db)
        count += 1
    return count
