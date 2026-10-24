from datetime import date
from pathlib import Path

from conftest import T
from pendant_recorder.dayfile import render_day, write_day


def test_render_matches_golden(root, db, cfg, seeded_2026_10_23_subset):
    out = render_day(db, date(2026, 10, 23), cfg, now_ms=T(23, 30, 0))
    assert out == (Path(__file__).parent / "golden" / "2026-10-23.md").read_text()


def test_clock_suspect_note(root, db, cfg, seeded_bad_clock_day):
    assert "> Clock was unset on the pendant" in render_day(db, date(2026, 10, 24), cfg, now_ms=0)


def test_orphan_star_line(root, db, cfg, seeded_orphan_star):
    assert "★ (no speech recorded nearby)" in render_day(db, date(2026, 10, 23), cfg, now_ms=0)


def test_write_day_marks_clean(root, db, cfg, seeded_2026_10_23_subset):
    db.mark_day_dirty(date(2026, 10, 23)); p = write_day(db, root, date(2026, 10, 23), cfg, now_ms=0)
    assert p.name == "2026-10-23.md" and db.days_dirty() == []


import dataclasses

from conftest import _press, _real_transcript
from pendant_recorder.dayfile import _duration
from pendant_recorder.group import rebuild_day

DAY = date(2026, 10, 23)


def _speech(db, clip_record, transcribed_at=None, **kw):
    c = dataclasses.replace(clip_record, classification=None, transcribed_at=None, **kw)
    db.add_clip(c)
    db.set_transcript(c.clip_id, _real_transcript(), "speech", transcribed_at or T(23, 0, 0))
    return c


def test_duration_forms():
    assert _duration(16_000) == "16 s"
    assert _duration(16 * 60_000) == "16 min"
    assert _duration((3 * 3600 + 16 * 60) * 1000) == "3h 16m"


def test_audio_kept_until_date(root, db, cfg, clip_record):
    _speech(db, clip_record)
    rebuild_day(db, DAY, cfg)
    out = render_day(db, DAY, cfg, now_ms=0)
    assert "Audio kept until 2026-11-06._" in out
    assert "## Starred" not in out and "stars: 0" in out


def test_audio_deleted(root, db, cfg, clip_record):
    c = _speech(db, clip_record)
    rebuild_day(db, DAY, cfg)
    db.clear_clip_path(c.clip_id)
    assert render_day(db, DAY, cfg, now_ms=0).endswith("Audio deleted._\n")


def test_pinned_heading(root, db, cfg, clip_record):
    _speech(db, clip_record)
    rebuild_day(db, DAY, cfg)
    db.pin("c-20261023-225609")
    out = render_day(db, DAY, cfg, now_ms=0)
    assert "### 22:56–22:56 · 16 s speech (pinned) {#c-20261023-225609}" in out
    assert out.rstrip().endswith("Audio kept._")


def test_noise_only_day(root, db, cfg, clip_record):
    db.add_clip(dataclasses.replace(clip_record, classification="noise", transcribed_at=T(23, 0, 0)))
    out = render_day(db, DAY, cfg, now_ms=0)
    assert "speech: 0 s across 0 conversations; 1 noise clip dropped" in out
    assert "## Starred" not in out and "## Conversations" not in out


def test_keep_noise_section(root, db, cfg, seeded_2026_10_23_subset):
    out = render_day(db, DAY, cfg, now_ms=0, keep_noise=True)
    assert "## Noise clips\n- 22:55:14 · 5.5 s · −44.2 dB\n- 23:01:25 · 5.5 s · −40.0 dB\n" in out


def test_keep_noise_unknown_loudness(root, db, cfg, clip_record):
    db.add_clip(dataclasses.replace(clip_record, classification="noise", mean_db=None))
    assert "· 16.0 s · n/a" in render_day(db, DAY, cfg, now_ms=0, keep_noise=True)


def test_day_without_audio_says_nothing_about_audio(root, db, cfg):
    db.add_event(_press(1, T(9, 0, 0)))
    out = render_day(db, DAY, cfg, now_ms=0)
    assert "★ (no speech recorded nearby)" in out
    assert out.endswith(f"_Transcribed with {cfg.whisper_model}._\n") and "Audio" not in out
