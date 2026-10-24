import os

from pendant_recorder.models import Segment, Transcript, Word
from pendant_recorder.transcribe import FakeTranscriber, MlxWhisperTranscriber, transcribe_pending


def test_mlx_result_mapping(monkeypatch, tmp_path):
    fake = {"text": " test one", "language": "en", "segments": [{"start": 0.0, "end": 2.32, "text": " test one", "avg_logprob": -0.293, "no_speech_prob": 0.0, "words": [{"start": 0.0, "end": 0.32, "word": " test", "probability": 0.49}]}]}
    monkeypatch.setattr("pendant_recorder.transcribe.mlx_whisper.transcribe", lambda *a, **k: fake)
    t = MlxWhisperTranscriber("m", "en").transcribe(tmp_path / "x.wav")
    assert t.model == "m" and t.segments[0].words[0].probability == 0.49 and t.segments[0].avg_logprob == -0.293
    assert os.environ["HF_HUB_OFFLINE"] == "1"


def test_transcribe_pending_marks_failures_and_continues(root, db, two_clips_with_audio):
    good = Transcript("ok", "en", "m", [Segment(0, 1, "ok", -0.2, 0.0, [Word(0, 1, "ok", 0.9), Word(0, 1, "ok", 0.9)])])
    tr = FakeTranscriber({two_clips_with_audio[0].clip_id: RuntimeError("boom"), two_clips_with_audio[1].clip_id: good})
    assert transcribe_pending(db, root, tr, classify=lambda c, t: "speech") == (1, 1)
    assert db.clip(two_clips_with_audio[0].clip_id).classification == "failed"
    assert db.clip(two_clips_with_audio[1].clip_id).classification == "speech"
    assert db.clips_needing_transcript() == []


def test_fake_default_and_unknown(tmp_path):
    d = Transcript("d", "en", "m", [])
    assert FakeTranscriber({}, default=d).transcribe(tmp_path / "a.wav") is d
    try:
        FakeTranscriber({}).transcribe(tmp_path / "a.wav")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")
