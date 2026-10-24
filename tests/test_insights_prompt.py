from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from conftest import T

from lavalier.insights import prompt
from lavalier.insights.prompt import (SYSTEM_PROMPT, ask_messages, day_text, estimate_tokens, resolve_moment,
                                      summarize_messages)
from lavalier.journal import day_view

GOLDEN = Path(__file__).parent / "golden"
DAY = date(2026, 10, 23)


def test_day_text_matches_the_golden_conversations_section(db, seeded_2026_10_23_subset, cfg):
    dt = day_text(db, DAY, cfg, now_ms=T(23, 30, 0))
    assert dt.text == (GOLDEN / "2026-10-23-daytext.md").read_text()
    assert dt.has_speech and not dt.truncated and dt.chars == len(dt.text) and dt.day == DAY
    assert dt.day_start_ms == T(0, 0, 0)


def test_day_text_is_the_day_files_conversations_minus_anchors(db, seeded_2026_10_23_subset, cfg):
    import re
    from lavalier.dayfile import render_day
    md = render_day(db, DAY, cfg, now_ms=T(23, 30, 0))
    section = md.split("## Conversations\n\n", 1)[1].rsplit("\n_Transcribed with", 1)[0]
    assert day_text(db, DAY, cfg, now_ms=T(23, 30, 0)).text == re.sub(r" \{#[^}]*\}", "", section)


def test_day_text_is_truncated_from_the_front_with_a_note_past_the_cap(db, seeded_2026_10_23_subset, cfg, monkeypatch):
    full = day_text(db, DAY, cfg, now_ms=T(23, 30, 0))
    monkeypatch.setattr(prompt, "MAX_CHARS", 80)
    assert len(full.text) > 80
    dt = day_text(db, DAY, cfg, now_ms=T(23, 30, 0))
    note = "[earlier part of the day omitted]\n"
    assert dt.truncated and dt.text.startswith(note) and len(dt.text) <= 80 + len(note)
    kept = dt.text[len(note):]
    assert full.text.endswith(kept) and full.text[-len(kept) - 1] == "\n"  # cut at a line boundary
    assert dt.chars == len(dt.text)


def test_day_text_without_speech_has_no_speech(db, cfg):
    dt = day_text(db, DAY, cfg, now_ms=T(23, 30, 0))
    assert not dt.has_speech and dt.text == "" and not dt.truncated and dt.chars == 0


def test_a_day_with_speech_and_an_orphan_star_has_speech(db, seeded_orphan_star, cfg):
    dt = day_text(db, DAY, cfg, now_ms=T(23, 30, 0))
    assert dt.has_speech and "★" not in dt.text.splitlines()[0]


def test_estimate_tokens_is_a_quarter_of_the_characters():
    assert estimate_tokens(401) == 100 and estimate_tokens(3) == 0


def test_summarize_messages_puts_the_text_after_the_instructions(db, seeded_2026_10_23_subset, cfg):
    dt = day_text(db, DAY, cfg, now_ms=T(23, 30, 0))
    msgs = summarize_messages(dt)
    assert msgs == [{"role": "user", "content": (
        "Summarise this day. Reply with JSON: summary (one short paragraph), follow_ups (each with text and the time "
        "[HH:MM:SS] of the line it comes from), people (names as written in the text), topics (two to four words each)."
        "\n\n" + dt.text)}]


def test_ask_messages_carry_the_question_then_the_text(db, seeded_2026_10_23_subset, cfg):
    dt = day_text(db, DAY, cfg, now_ms=T(23, 30, 0))
    assert ask_messages(dt, "Who called?") == [{"role": "user", "content": (
        "Answer the question from this day's text only. If the text does not say, say so.\n\n"
        "Question: Who called?\n\n" + dt.text)}]


def test_system_prompt_is_pinned():
    assert SYSTEM_PROMPT == (
        "You read one day of a person's own transcribed conversations, recorded by a microphone they wear. "
        "Lines carry the time of day as [HH:MM:SS]; a line with \u2605 marks a moment the person starred. "
        "Write for that person, in plain language, in their own words where you can. "
        "Never invent names, events or decisions that are not in the text. "
        "Keep the summary to one short paragraph. "
        "A follow-up is something the person said they would do, decide, or look into; "
        "give each one the time of the line it comes from. "
        "People are names that appear in the text, as written. "
        "Topics are two to four words each. "
        "Answer only from the text; when the text does not say, say so.")


def test_cut_front_without_a_newline_keeps_the_raw_tail(monkeypatch):
    monkeypatch.setattr(prompt, "MAX_CHARS", 10)
    out = prompt._cut_front("x" * 50)
    assert out == prompt.OMITTED + "x" * 10


@pytest.fixture
def view(db, seeded_2026_10_23_subset, cfg):
    return day_view(db, DAY, cfg, now_ms=T(23, 30, 0))


def test_resolve_moment_picks_the_last_line_at_or_before(view):
    lines = [ln for c in view.conversations for ln in c.lines]
    first = lines[0]
    assert resolve_moment(view, first.at_ms) == f"{first.clip_id}-{first.seq}"
    later = [ln for ln in lines if ln.at_ms > first.at_ms][0]
    assert resolve_moment(view, later.at_ms + 1) == f"{later.clip_id}-{later.seq}"
    if later.at_ms - first.at_ms <= 60_000:
        assert resolve_moment(view, later.at_ms - 1) == f"{first.clip_id}-{first.seq}"


def test_resolve_moment_outside_any_line_gives_none(view):
    lines = [ln for c in view.conversations for ln in c.lines]
    assert resolve_moment(view, lines[0].at_ms - 1) is None
    assert resolve_moment(view, lines[-1].at_ms + 60_001) is None
    assert resolve_moment(view, lines[-1].at_ms + 60_000) is not None
