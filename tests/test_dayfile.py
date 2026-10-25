from datetime import date
from pathlib import Path

from conftest import T
from lavalier.dayfile import render_day, write_day


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
from lavalier.dayfile import duration
from lavalier.group import rebuild_day

DAY = date(2026, 10, 23)


def _speech(db, clip_record, transcribed_at=None, **kw):
    c = dataclasses.replace(clip_record, classification=None, transcribed_at=None, **kw)
    db.add_clip(c)
    db.set_transcript(c.clip_id, _real_transcript(), "speech", transcribed_at or T(23, 0, 0))
    return c


def testduration_forms():
    assert duration(16_000) == "16 s"
    assert duration(16 * 60_000) == "16 min"
    assert duration((3 * 3600 + 16 * 60) * 1000) == "3h 16m"


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


def test_golden_day_file_without_insights_is_unchanged(root, db, cfg, seeded_2026_10_23_subset):
    out = render_day(db, date(2026, 10, 23), cfg, now_ms=T(23, 30, 0))
    assert db.insight(date(2026, 10, 23)) is None and "## Insights" not in out
    assert out == (Path(__file__).parent / "golden" / "2026-10-23.md").read_text()


def test_a_stored_insight_renders_after_the_conversations(root, db, cfg, seeded_2026_10_23_subset):
    from datetime import datetime

    from lavalier.insights.schema import FollowUp, Insight
    at = int(datetime(2026, 10, 23, 22, 56, 13).timestamp() * 1000)
    gen = int(datetime(2026, 10, 24, 4, 12).timestamp() * 1000)
    db.set_insight(date(2026, 10, 23), provider="anthropic", model="claude-opus-5-5", prompt_version=1,
                   generated_ms=gen, input_chars=100, insight=Insight(
                       "A short pendant test: two rounds of counting to three, both starred.",
                       [FollowUp("Check that both stars landed", at, "clip_20261024T055609.085Z-1")],
                       ["Remy", "Daddy"], ["pendant test", "star button"]))
    out = render_day(db, date(2026, 10, 23), cfg, now_ms=gen)
    assert out == (Path(__file__).parent / "golden" / "2026-10-23-with-insights.md").read_text()


# --- final fix wave

def _insight(db, *, provider="anthropic", summary="A summary.", follow_up="Call back"):
    from datetime import datetime

    from lavalier.insights.schema import FollowUp, Insight
    gen = int(datetime(2026, 10, 24, 4, 12).timestamp() * 1000)
    db.set_insight(date(2026, 10, 23), provider=provider, model="m1", prompt_version=1, generated_ms=gen,
                   input_chars=100, insight=Insight(summary, [FollowUp(follow_up, None, None)], [], []))
    return gen


def test_an_endpoint_run_names_the_endpoint_not_openai(root, db, cfg, seeded_2026_10_23_subset):
    gen = _insight(db, provider="openai@llm.example.net:8443")
    out = render_day(db, date(2026, 10, 23), cfg, now_ms=gen)
    assert "_Insights by m1 (the endpoint at llm.example.net:8443) at 04:12._" in out and "OpenAI" not in out
    _insight(db, provider="openai")
    assert "(OpenAI)" in render_day(db, date(2026, 10, 23), cfg, now_ms=gen)


def test_newlines_in_a_summary_or_a_follow_up_are_collapsed(root, db, cfg, seeded_2026_10_23_subset):
    gen = _insight(db, summary="First line.\n\n## Not a heading\nlast", follow_up="Call\nback\r\n  soon")
    out = render_day(db, date(2026, 10, 23), cfg, now_ms=gen)
    assert "First line. ## Not a heading last\n" in out and "\n## Not a heading" not in out
    assert "- Call back soon\n" in out


def test_labelled_heading(root, db, cfg, clip_record):
    _speech(db, clip_record)
    rebuild_day(db, DAY, cfg)
    db.set_conversation_label("c-20261023-225609", "Weekly sync")
    assert "### 22:56–22:56 · 16 s speech · Weekly sync {#c-20261023-225609}" in render_day(db, DAY, cfg, now_ms=0)
    db.pin("c-20261023-225609")
    assert "16 s speech · Weekly sync (pinned) {#c-20261023-225609}" in render_day(db, DAY, cfg, now_ms=0)


def test_labelled_heading_with_stars_and_a_multiline_label_stays_one_line(db, cfg, seeded_2026_10_23_subset):
    cid = db.conversations_for_day(DAY)[0].conversation_id
    db.set_conversation_label(cid, "Weekly\nsync")
    out = render_day(db, DAY, cfg, now_ms=0)
    assert " · Weekly sync {#" in out and "Weekly\n" not in out


def test_a_blank_label_is_no_label_and_inner_whitespace_collapses(db, cfg, seeded_2026_10_23_subset):
    cid = db.conversations_for_day(DAY)[0].conversation_id
    db.set_conversation_label(cid, " \n ")
    assert f"speech ★★ {{#{cid}}}" in render_day(db, DAY, cfg, now_ms=0)
    db.set_conversation_label(cid, "  Weekly \t sync ")
    assert " · Weekly sync {#" in render_day(db, DAY, cfg, now_ms=0)
