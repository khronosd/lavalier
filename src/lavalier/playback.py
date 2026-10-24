"""On-demand AAC transcodes of clip audio, cached under the state root, for the window's WKWebView."""
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from lavalier.audio import AudioToolError, ffmpeg_path
from lavalier.config import Config
from lavalier.db import Database
from lavalier.paths import Paths


log = logging.getLogger(__name__)


class PlaybackError(Exception):
    pass


class AudioExpired(PlaybackError):
    """The clip's audio was deleted by retention."""


class UnknownClip(PlaybackError):
    pass


def cache_dir(paths: Paths) -> Path:
    d = paths.cache / "aac"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _transcode(src: Path, tmp: Path, encoder: str) -> subprocess.CompletedProcess:
    # -f ogg: same probe-collision workaround as audio.py (Ogg mistaken for MPEG-TS).
    # -movflags +faststart: the index goes first, so the player can start before the last byte.
    # -f ipod: the temp file has no .m4a suffix, so name the muxer explicitly.
    return subprocess.run(
        [ffmpeg_path() or "ffmpeg", "-v", "error", "-y", "-f", "ogg", "-i", str(src), "-c:a", encoder, "-b:a", "64k",
         "-movflags", "+faststart", "-f", "ipod", str(tmp)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def locate(db: Database, paths: Paths, clip_id: str, *, cfg: Config, now_ms: int) -> tuple[Path, Path]:
    """The clip's Opus source and its cache path; the database half of aac_path. Audio past its
    retention deadline is expired even before the sweep deletes the file."""
    from lavalier.retention import audio_expired  # retention imports this module for evict/sweep_cache
    clip = db.clip(clip_id)
    if clip is None:
        raise UnknownClip(clip_id)
    if not clip.path or audio_expired(db, clip, cfg, now_ms=now_ms):
        raise AudioExpired(clip_id)
    return paths.root / clip.path, cache_dir(paths) / f"{clip_id}.m4a"


def transcode(src: Path, dst: Path) -> None:
    """Transcode src to dst through a temp file beside it; no database involved, so it may run in a thread."""
    fd, name = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.stem}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        r = _transcode(src, tmp, "aac_at")
        if r.returncode != 0:
            r = _transcode(src, tmp, "aac")
        if r.returncode != 0:
            raise AudioToolError(f"ffmpeg failed ({r.returncode}) transcoding {src}: {r.stderr.strip()}")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def aac_path(db: Database, paths: Paths, clip_id: str, *, cfg: Config, now_ms: int) -> Path:
    src, dst = locate(db, paths, clip_id, cfg=cfg, now_ms=now_ms)
    if not dst.exists():
        transcode(src, dst)
    return dst


def evict(paths: Paths, clip_id: str) -> None:
    (paths.cache / "aac" / f"{clip_id}.m4a").unlink(missing_ok=True)


def sweep_cache(db: Database, paths: Paths) -> int:
    """Remove every cached m4a whose clip is unknown or has no audio left; returns how many went.
    Catches what evict cannot: a failed eviction, or a transcode that finished after retention
    deleted its source. Temp files of transcodes in flight are left alone."""
    d = paths.cache / "aac"
    if not d.is_dir():
        return 0
    removed = 0
    for f in sorted(d.glob("*.m4a")):
        clip = db.clip(f.stem)
        if clip is not None and clip.path:
            continue
        try:
            f.unlink(missing_ok=True)
        except OSError as e:
            log.warning("could not remove the stale cached AAC %s: %s", f.name, e)
            continue
        removed += 1
    return removed
