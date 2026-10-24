"""End-to-end run on the real 2026-10-23 capture: real decode, real ffmpeg loudness, fake model."""

from datetime import date
from pathlib import Path

import pytest

from conftest import T, speech_transcript, thank_you_transcript, _real_transcript
from pendant_recorder.pipeline import import_and_process
from pendant_recorder.transcribe import FakeTranscriber

FIXTURE = Path("/Users/khronos/Repos/pendant-lab/artifacts/capture-2026-10-23.bin")
DAY = date(2026, 10, 23)


def fixture_transcriber() -> FakeTranscriber:
    return FakeTranscriber(
        {
            "clip_20261024T055514.111Z": thank_you_transcript(),
            "clip_20261024T060125.346Z": thank_you_transcript(),
            "clip_20261024T055609.085Z": _real_transcript(),
        },
        default=speech_transcript(),
    )


@pytest.mark.slow
@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture capture not present")
def test_real_capture_end_to_end(root, db, cfg):
    """8058 messages yield exactly 7908 new pages, matching the 7908 distinct audio/event
    pages (indices 5..7912) counted in NOTES.md; the brief allowed up to 8058. The 5 log
    pages (0..4) did not add to the count (not investigated further). Loudness is real
    ffmpeg; only the speech model is faked."""
    imp, rep = import_and_process(
        db, root, cfg, fixture_transcriber(), FIXTURE, now_ms=T(23, 30, 0), capture_day=DAY)
    assert imp.messages == 8058 and imp.pages_new == 7908 and imp.pages_duplicate == 0
    clips = db.clips_for_day(DAY)
    assert len(clips) == 108
    assert sum(c.chunk_count for c in clips) == 588_872
    assert db.clip("clip_20261024T055514.111Z").classification == "noise"
    assert db.clip("clip_20261024T060125.346Z").classification == "noise"
    assert db.clip("clip_20261024T055609.085Z").classification == "speech"
    convs = db.conversations_for_day(DAY)
    starred = [c for c in convs if c.star_ms]
    assert len(starred) == 1 and starred[0].star_ms == [1792821367981, 1792821372732]
    md = (root.days / "2026-10-23.md").read_text()
    assert "22:56:07 ★" in md and "22:56:12 ★" in md
    # re-importing the same capture changes nothing
    imp2, _ = import_and_process(
        db, root, cfg, fixture_transcriber(), FIXTURE, now_ms=T(23, 30, 0), capture_day=DAY)
    assert imp2.pages_new == 0 and len(db.clips_for_day(DAY)) == 108
