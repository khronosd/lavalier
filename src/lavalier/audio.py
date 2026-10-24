"""ffmpeg helpers: WAV conversion for the transcriber and loudness measurement."""
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from lavalier.db import Database
from lavalier.paths import Paths

log = logging.getLogger(__name__)

_MEAN = re.compile(r"mean_volume:\s*(-?[\d.]+|-?inf)\s*dB")
_MAX = re.compile(r"max_volume:\s*(-?[\d.]+|-?inf)\s*dB")


class AudioToolError(RuntimeError):
    pass


# launchd starts the app with a bare PATH (/usr/bin:/bin:...); Homebrew's ffmpeg lives here.
FFMPEG_FALLBACKS = (Path("/opt/homebrew/bin/ffmpeg"), Path("/usr/local/bin/ffmpeg"))


def ffmpeg_path() -> Optional[str]:
    """The ffmpeg binary: the one on PATH, else a Homebrew location; None when there is none."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in FFMPEG_FALLBACKS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


def ensure_ffmpeg_on_path() -> Optional[str]:
    """Put ffmpeg's directory first on PATH when `ffmpeg` is not findable by name: mlx-whisper runs it
    by name. Returns the binary's path, or None when there is none. Safe to call more than once."""
    found = ffmpeg_path()
    if found is None:
        return None
    directory = str(Path(found).parent)
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if shutil.which("ffmpeg") is None and directory not in parts:
        os.environ["PATH"] = os.pathsep.join([directory] + parts)
    return found


# Force the Ogg demuxer (-f ogg) below: with a stream serial ending in 0x47 and uniform page sizes,
# ffmpeg's probe mistakes the file for MPEG-TS (sync byte every 192 bytes) and rejects it.
def to_wav16k(src: Path, dst: Path) -> None:
    r = subprocess.run(
        [ffmpeg_path() or "ffmpeg", "-v", "error", "-y", "-f", "ogg", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise AudioToolError(f"ffmpeg failed ({r.returncode}) converting {src}: {r.stderr.strip()}")


def loudness(path: Path) -> tuple[float, float]:
    r = subprocess.run(
        [ffmpeg_path() or "ffmpeg", "-v", "info", "-f", "ogg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
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
