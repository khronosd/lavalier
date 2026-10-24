import shutil
import subprocess

import pytest

from pendant_recorder.audio import AudioToolError, ffmpeg_available, loudness, measure_loudness, to_wav16k

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")


@needs_ffmpeg
def test_loudness_of_silence_and_tone(tmp_path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1", str(tmp_path / "s.wav")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-af", "volume=18dB", "-t", "1", str(tmp_path / "t.wav")], check=True)
    mean_s, _ = loudness(tmp_path / "s.wav")
    mean_t, max_t = loudness(tmp_path / "t.wav")
    assert mean_s < -80 and -4 < mean_t < -2 and max_t <= 0


@needs_ffmpeg
def test_to_wav16k_produces_mono_16k(tmp_path, opus_clip):
    to_wav16k(opus_clip, tmp_path / "x.wav")
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", str(tmp_path / "x.wav")], capture_output=True, text=True).stdout
    assert info.strip() == "16000,1"


@needs_ffmpeg
def test_to_wav16k_raises_on_missing_input(tmp_path):
    with pytest.raises(AudioToolError):
        to_wav16k(tmp_path / "nope.opus", tmp_path / "x.wav")


def test_ffmpeg_available_matches_which():
    assert ffmpeg_available() == bool(shutil.which("ffmpeg"))


@needs_ffmpeg
def test_measure_loudness_updates_clips_and_skips_missing(root, db, clip_record, opus_clip):
    from dataclasses import replace
    dest = root.root / clip_record.path
    dest.parent.mkdir(parents=True)
    shutil.copy(opus_clip, dest)
    db.add_clip(clip_record)
    gone = replace(clip_record, clip_id="clip_gone", path="audio/2026-10-23/gone.opus")
    db.add_clip(gone)
    assert measure_loudness(db, root) == 1
    c = db.clip(clip_record.clip_id)
    assert c.mean_db is not None and c.peak_db is not None
    assert db.clip("clip_gone").mean_db is None


@needs_ffmpeg
def test_measure_loudness_isolates_a_corrupt_clip(root, db, clip_record, opus_clip):
    from dataclasses import replace
    good = root.root / clip_record.path
    good.parent.mkdir(parents=True)
    shutil.copy(opus_clip, good)
    db.add_clip(clip_record)
    bad = replace(clip_record, clip_id="clip_bad", path="audio/2026-10-23/bad.opus", first_ms=clip_record.first_ms - 1000)
    (root.root / bad.path).write_bytes(b"")
    db.add_clip(bad)
    assert measure_loudness(db, root) == 1
    assert db.clip("clip_bad").classification == "failed"
    assert db.days_dirty() == [bad.day]
    assert db.clip(clip_record.clip_id).mean_db is not None
    assert measure_loudness(db, root) == 0  # the failed clip is not retried
