from lavalier.config import Config
import shutil
from pathlib import Path
import subprocess

import pytest

from lavalier.playback import AudioExpired, UnknownClip, aac_path, evict

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")


@needs_ffmpeg
def test_transcode_is_cached_and_plays_as_aac(root, db, two_clips_with_audio):
    p = aac_path(db, root, two_clips_with_audio[0].clip_id, cfg=Config(), now_ms=0)
    assert p.suffix == ".m4a" and p.exists() and p.parent == root.cache / "aac"
    mtime = p.stat().st_mtime
    assert aac_path(db, root, two_clips_with_audio[0].clip_id, cfg=Config(), now_ms=0) == p and p.stat().st_mtime == mtime
    codec = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
    assert codec == "aac"
    assert [f.name for f in p.parent.iterdir()] == [p.name]


def test_expired_and_unknown_clips_are_distinct_errors(root, db, two_clips_with_audio):
    db.clear_clip_path(two_clips_with_audio[0].clip_id)
    with pytest.raises(AudioExpired):
        aac_path(db, root, two_clips_with_audio[0].clip_id, cfg=Config(), now_ms=0)
    with pytest.raises(UnknownClip):
        aac_path(db, root, "clip_nope", cfg=Config(), now_ms=0)


def test_evict_missing_is_silent(root):
    evict(root, "clip_nope")


def test_falls_back_to_builtin_encoder(root, db, two_clips_with_audio, monkeypatch):
    import lavalier.playback as pb
    calls = []

    def fake_run(cmd, **kw):
        assert cmd[cmd.index("-movflags") + 1] == "+faststart" and cmd[-3:-1] == ["-f", "ipod"]
        calls.append(cmd[cmd.index("-c:a") + 1])
        if cmd[cmd.index("-c:a") + 1] == "aac_at":
            return subprocess.CompletedProcess(cmd, 1, "", "no aac_at")
        Path(cmd[-1]).write_bytes(b"x")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pb.subprocess, "run", fake_run)
    p = aac_path(db, root, two_clips_with_audio[0].clip_id, cfg=Config(), now_ms=0)
    assert calls == ["aac_at", "aac"] and p.read_bytes() == b"x"


def test_both_encoders_failing_raises(root, db, two_clips_with_audio, monkeypatch):
    import lavalier.playback as pb
    from lavalier.audio import AudioToolError
    monkeypatch.setattr(pb.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    with pytest.raises(AudioToolError, match="boom"):
        aac_path(db, root, two_clips_with_audio[0].clip_id, cfg=Config(), now_ms=0)
    assert list((root.cache / "aac").iterdir()) == []


DAY_MS = 86_400_000


def test_audio_past_its_retention_deadline_is_expired_even_while_its_file_exists(root, db, seeded_retention_day):
    old, starred, fresh, failed = seeded_retention_day
    now = old.transcribed_at + 14 * DAY_MS  # the sweep has not run: every file is still there
    assert (root.root / old.path).exists()
    with pytest.raises(AudioExpired):
        aac_path(db, root, old.clip_id, cfg=Config(), now_ms=now)
    from lavalier.playback import locate
    for kept in (starred, fresh, failed):  # protected, within the window, never deleted
        src, _ = locate(db, root, kept.clip_id, cfg=Config(), now_ms=now)
        assert src == root.root / kept.path
    longer = Config(retention_days=30)  # the deadline follows the setting
    assert locate(db, root, old.clip_id, cfg=longer, now_ms=now)[0] == root.root / old.path
