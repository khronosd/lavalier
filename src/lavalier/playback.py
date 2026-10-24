"""On-demand AAC transcodes of clip audio, cached under the state root, for the window's WKWebView."""
import os
import subprocess
import tempfile
from pathlib import Path

from lavalier.audio import AudioToolError
from lavalier.db import Database
from lavalier.paths import Paths


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
    # -f ipod: the temp file has no .m4a suffix, so name the muxer explicitly.
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "ogg", "-i", str(src), "-c:a", encoder, "-b:a", "64k",
         "-f", "ipod", str(tmp)],
        capture_output=True, text=True,
    )


def aac_path(db: Database, paths: Paths, clip_id: str) -> Path:
    clip = db.clip(clip_id)
    if clip is None:
        raise UnknownClip(clip_id)
    if not clip.path:
        raise AudioExpired(clip_id)
    dst = cache_dir(paths) / f"{clip_id}.m4a"
    if dst.exists():
        return dst
    src = paths.root / clip.path
    fd, name = tempfile.mkstemp(dir=dst.parent, prefix=f".{clip_id}.", suffix=".tmp")
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
    return dst


def evict(paths: Paths, clip_id: str) -> None:
    (paths.cache / "aac" / f"{clip_id}.m4a").unlink(missing_ok=True)
