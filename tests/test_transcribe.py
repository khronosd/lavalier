import os

import pytest

from lavalier.models import Segment, Transcript, Word
from lavalier.transcribe import FakeTranscriber, MlxWhisperTranscriber, transcribe_pending


def test_mlx_result_mapping(monkeypatch, tmp_path):
    fake = {"text": " test one", "language": "en", "segments": [{"start": 0.0, "end": 2.32, "text": " test one", "avg_logprob": -0.293, "no_speech_prob": 0.0, "words": [{"start": 0.0, "end": 0.32, "word": " test", "probability": 0.49}]}]}
    monkeypatch.setattr("lavalier.transcribe.mlx_whisper.transcribe", lambda *a, **k: fake)
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
    assert db.days_dirty() == [two_clips_with_audio[0].day]


def test_fake_default_and_unknown(tmp_path):
    d = Transcript("d", "en", "m", [])
    assert FakeTranscriber({}, default=d).transcribe(tmp_path / "a.wav") is d
    try:
        FakeTranscriber({}).transcribe(tmp_path / "a.wav")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_missing_tool_aborts_transcription_and_leaves_clips_pending(root, db, two_clips_with_audio):
    tr = FakeTranscriber({c.clip_id: FileNotFoundError("ffmpeg") for c in two_clips_with_audio})
    with pytest.raises(FileNotFoundError):
        transcribe_pending(db, root, tr, classify=lambda c, t: "speech")
    assert len(db.clips_needing_transcript()) == 2


def test_mlx_unavailable_until_the_model_is_in_the_hf_hub_cache(monkeypatch, tmp_path):
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(tmp_path))
    tr = MlxWhisperTranscriber("org/model", "en")
    assert "org/model is not cached" in tr.unavailable_reason()
    (tmp_path / "models--org--model").mkdir()
    assert tr.unavailable_reason() is None


def test_mlx_nan_confidence_becomes_unknown(monkeypatch, tmp_path):
    # mlx_whisper 0.4.3 reports NaN for a window whose log-probabilities collapsed; sqlite would
    # store it as NULL, so the transcriber hands it over as "unknown" explicitly.
    nan = float("nan")
    fake = {"text": " hi", "language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": " hi",
            "avg_logprob": nan, "no_speech_prob": nan, "words": [{"start": 0.0, "end": 1.0, "word": " hi", "probability": nan}]}]}
    monkeypatch.setattr("lavalier.transcribe.mlx_whisper.transcribe", lambda *a, **k: fake)
    t = MlxWhisperTranscriber("m", "en").transcribe(tmp_path / "x.wav")
    s = t.segments[0]
    assert s.avg_logprob is None and s.no_speech_prob is None and s.words[0].probability is None
