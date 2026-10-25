import dataclasses
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from conftest import T, _press
from lavalier.group import rebuild_day
from lavalier.insights import stage
from lavalier.insights.keys import KeychainError
from lavalier.insights.providers.base import ProviderCheck, ProviderError
from lavalier.insights.schema import PROMPT_VERSION, Insight
from lavalier.insights.stage import (
    DAY_COMPLETE_HOUR, NO_SPEECH, ask_day, day_is_complete, due_days, estimate, generate_day,
)
from lavalier.pipeline import status_summary

DAY = date(2026, 10, 23)
GOLDEN = Path(__file__).parent / "golden"
SRC = Path(__file__).parent.parent / "src" / "lavalier" / "insights"

REPLY = {
    "summary": "A short pendant test: two rounds of counting to three, both starred.",
    "follow_ups": [{"text": "Check that both stars landed", "time": "22:56:13"}],
    "people": ["Remy", "Daddy"],
    "topics": ["pendant test", "star button"],
}


def T_next(h, m, s=0, ms=0) -> int:
    """Local 2026-10-24 timestamp in ms."""
    return int(datetime(2026, 10, 24, h, m, s, ms * 1000).timestamp() * 1000)


def at(day: date, h=12, m=0) -> int:
    return int(datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m).timestamp() * 1000)


class FakeProvider:
    def __init__(self, reply=None, *, error=None, exc=None, answer="An answer.", cost="about $0.20 per 3-hour day",
                 name="anthropic", model="claude-opus-5-5"):
        self.name, self.model = name, model
        self.reply = REPLY if reply is None else reply
        self.error, self.exc, self.answer, self.cost = error, exc, answer, cost
        self.calls: list[tuple] = []

    def summarize(self, dt):
        self.calls.append(("summarize", dt.day))
        if self.exc is not None:
            raise self.exc
        if self.error is not None:
            raise ProviderError(self.error)
        return self.reply

    def ask(self, dt, question):
        self.calls.append(("ask", dt.day, question))
        if self.error is not None:
            raise ProviderError(self.error)
        return self.answer

    def check(self):
        return ProviderCheck(True, "ok", [])

    def facts(self):
        return {"sends": "text", "to": "Anthropic", "cost": self.cost}


NOW = T_next(4, 12)


# --- generate_day

def test_generate_stores_the_insight_with_resolved_moments_and_rewrites_the_day_file(root, db, seeded_2026_10_23_subset, cfg):
    r = generate_day(db, root, cfg, FakeProvider(), DAY, now_ms=NOW)
    assert r.state == "done" and r.error is None
    assert (r.provider, r.model, r.prompt_version, r.generated_ms) == ("anthropic", "claude-opus-5-5", PROMPT_VERSION, NOW)
    assert r.input_chars > 0
    fu = r.insight.follow_ups[0]
    assert fu.line_id == "clip_20261024T055609.085Z-1" and fu.text == "Check that both stars landed"
    assert db.insight(DAY) == r and db.days_dirty() == []
    assert (root.days / "2026-10-23.md").read_text() == (GOLDEN / "2026-10-23-with-insights.md").read_text()


@pytest.mark.parametrize("make", [
    lambda: FakeProvider(error="timed out"),
    lambda: FakeProvider(exc=KeychainError("The Keychain refused: locked")),
    lambda: FakeProvider(reply={"summary": "x"}),
])
def test_a_failed_generation_stores_an_error_and_leaves_the_day_file_alone(root, db, seeded_2026_10_23_subset, cfg, make):
    db.mark_day_dirty(DAY)
    from lavalier.pipeline import write_dirty_days
    write_dirty_days(db, root, cfg, now_ms=NOW)
    f = root.days / "2026-10-23.md"
    before, mtime = f.read_text(), f.stat().st_mtime_ns
    r = generate_day(db, root, cfg, make(), DAY, now_ms=NOW)
    assert r.state == "error" and r.insight is None and r.error
    assert (r.provider, r.model, r.generated_ms) == ("anthropic", "claude-opus-5-5", NOW) and r.input_chars > 0
    assert db.insight(DAY) == r
    assert f.read_text() == before and f.stat().st_mtime_ns == mtime


def test_a_failed_generation_keeps_the_provider_message(root, db, seeded_2026_10_23_subset, cfg):
    r = generate_day(db, root, cfg, FakeProvider(error="timed out"), DAY, now_ms=NOW)
    assert r.error == "timed out"
    r = generate_day(db, root, cfg, FakeProvider(reply={"summary": "x"}), DAY, now_ms=NOW)
    assert r.error == "follow_ups is missing"


def test_a_programming_error_propagates(root, db, seeded_2026_10_23_subset, cfg):
    with pytest.raises(ZeroDivisionError):
        generate_day(db, root, cfg, FakeProvider(exc=ZeroDivisionError()), DAY, now_ms=NOW)
    assert db.insight(DAY) is None


def test_a_day_without_speech_is_not_sent(root, db, cfg):
    db.add_event(_press(7000, T(22, 50, 0)))  # a star alone: no clips, no speech
    rebuild_day(db, DAY, cfg)
    p = FakeProvider()
    r = generate_day(db, root, cfg, p, DAY, now_ms=NOW)
    assert r.state == "error" and r.error == NO_SPEECH and p.calls == []
    assert not (root.days / "2026-10-23.md").exists()


def test_follow_ups_keep_their_text_when_the_moment_has_no_line(root, db, seeded_2026_10_23_subset, cfg):
    reply = {**REPLY, "follow_ups": [{"text": "Book the dentist", "time": "10:00:00"}]}
    r = generate_day(db, root, cfg, FakeProvider(reply), DAY, now_ms=NOW)
    fu = r.insight.follow_ups[0]
    assert fu.line_id is None and fu.text == "Book the dentist" and fu.at_ms == T(10, 0, 0)
    assert "- [10:00:00] Book the dentist" in (root.days / "2026-10-23.md").read_text()


# --- day file section

def test_the_day_file_omits_empty_subsections(root, db, seeded_2026_10_23_subset, cfg):
    from lavalier.dayfile import render_day
    generate_day(db, root, cfg, FakeProvider({**REPLY, "follow_ups": [], "people": []}), DAY, now_ms=NOW)
    out = render_day(db, DAY, cfg, now_ms=NOW)
    assert "## Insights" in out and "### Topics" in out
    assert "### Follow-ups" not in out and "### People" not in out


def test_an_error_row_adds_no_section(root, db, seeded_2026_10_23_subset, cfg):
    from lavalier.dayfile import render_day
    generate_day(db, root, cfg, FakeProvider(error="timed out"), DAY, now_ms=NOW)
    assert render_day(db, DAY, cfg, now_ms=T(23, 30, 0)) == (GOLDEN / "2026-10-23.md").read_text()


# --- the due rule

def test_day_is_complete_after_four_next_morning():
    assert DAY_COMPLETE_HOUR == 4
    assert not day_is_complete(DAY, T(23, 59, 59))
    assert not day_is_complete(DAY, T_next(3, 59))
    assert day_is_complete(DAY, T_next(4, 0, 1))


def _speech_day(db, clip_record, day: date, n: int):
    c = dataclasses.replace(clip_record, clip_id=f"clip_due_{n}", day=day, first_ms=at(day), last_ms=at(day) + 15000,
                            classification="speech")
    db.add_clip(c)


@pytest.fixture
def five_speech_days(db, clip_record):
    days = [date(2026, 10, 18) + timedelta(days=i) for i in range(5)]  # 18th .. 22nd
    for i, d in enumerate(days):
        _speech_day(db, clip_record, d, i)
    return days


def _cfg(cfg, **kw):
    return dataclasses.replace(cfg, insights_provider="anthropic", **kw)


def test_due_days_skips_today_done_error_and_days_before_enabling(db, cfg, clip_record, five_speech_days):
    d18, d19, d20, d21, d22 = five_speech_days
    today = date(2026, 10, 24)
    _speech_day(db, clip_record, today, 9)
    _speech_day(db, clip_record, DAY, 10)  # 23rd: not complete until 04:00 on the 24th
    db.set_insight(d20, provider="anthropic", model="m", prompt_version=1, generated_ms=0, input_chars=1,
                   insight=Insight("s", [], [], []))
    db.set_insight_error(d21, provider="anthropic", model="m", prompt_version=1, generated_ms=0, input_chars=1,
                         error="timed out")
    enabled = int(datetime(2026, 10, 19, 4, 0).timestamp() * 1000)  # the 18th completed exactly then
    now = T_next(3, 0)
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=enabled) == [d18, d19, d22]
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=enabled + 1) == [d19, d22]
    assert due_days(db, _cfg(cfg), now_ms=T_next(4, 0, 1), enabled_at_ms=enabled) == [d18, d19, d22, DAY]


def test_due_days_ignores_days_without_speech(db, cfg, clip_record):
    c = dataclasses.replace(clip_record, clip_id="clip_noise", day=date(2026, 10, 20), first_ms=at(date(2026, 10, 20)),
                            last_ms=at(date(2026, 10, 20)) + 5000, classification="noise")
    db.add_clip(c)
    assert due_days(db, _cfg(cfg), now_ms=T_next(12, 0), enabled_at_ms=0) == []


def test_due_days_is_empty_when_auto_is_off(db, cfg, five_speech_days):
    now = T_next(12, 0)
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=0) == five_speech_days
    assert due_days(db, _cfg(cfg, insights_auto=False), now_ms=now, enabled_at_ms=0) == []
    assert due_days(db, cfg, now_ms=now, enabled_at_ms=0) == []  # no provider chosen
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=None) == []


# --- ask_day and estimate

def test_ask_day_answers_from_the_provider(db, seeded_2026_10_23_subset, cfg):
    p = FakeProvider(answer="You counted to three.")
    assert ask_day(db, cfg, p, DAY, "What did I count?", now_ms=NOW) == "You counted to three."
    assert p.calls == [("ask", DAY, "What did I count?")]


def test_ask_day_without_speech_is_not_sent(db, cfg):
    p = FakeProvider()
    assert ask_day(db, cfg, p, DAY, "Anything?", now_ms=NOW) == NO_SPEECH and p.calls == []


def test_ask_day_lets_provider_errors_through(db, seeded_2026_10_23_subset, cfg):
    with pytest.raises(ProviderError, match="timed out"):
        ask_day(db, cfg, FakeProvider(error="timed out"), DAY, "Q?", now_ms=NOW)


def test_estimate_scales_the_cost_by_tokens(db, seeded_2026_10_23_subset, cfg, monkeypatch):
    real = stage.day_text

    def big(db, day, cfg, *, now_ms):
        return dataclasses.replace(real(db, day, cfg, now_ms=now_ms), chars=80_000)  # 20k tokens

    monkeypatch.setattr(stage, "day_text", big)
    e = estimate(db, cfg, [DAY, DAY], FakeProvider(), now_ms=NOW)
    assert e == {"days": 2, "tokens": 40_000, "cost": "about $0.20"}
    e = estimate(db, cfg, [DAY], FakeProvider(cost="about $0.0048 per 3-hour day"), now_ms=NOW)
    assert e["cost"] == "about $0.0024"
    e = estimate(db, cfg, [DAY] * 30, FakeProvider(cost="about $0.48 per 3-hour day"), now_ms=NOW)
    assert e["cost"] == "about $7.20"
    e = estimate(db, cfg, [DAY] * 300, FakeProvider(cost="about $0.48 per 3-hour day"), now_ms=NOW)
    assert e["cost"] == "about $72"


def test_estimate_uses_the_real_day_text(db, seeded_2026_10_23_subset, cfg):
    from lavalier.insights.prompt import day_text, estimate_tokens
    chars = day_text(db, DAY, cfg, now_ms=NOW).chars
    e = estimate(db, cfg, [DAY], FakeProvider(), now_ms=NOW)
    assert e["days"] == 1 and e["tokens"] == estimate_tokens(chars) and e["cost"].startswith("about $")


def test_estimate_free_and_unpriced(db, seeded_2026_10_23_subset, cfg):
    assert estimate(db, cfg, [DAY], FakeProvider(cost="free, runs on this Mac"), now_ms=NOW)["cost"] == \
        "free, runs on this Mac"
    assert estimate(db, cfg, [DAY], FakeProvider(cost="set by that endpoint"), now_ms=NOW)["cost"] == \
        "set by that endpoint"
    assert estimate(db, cfg, [], FakeProvider(), now_ms=NOW) == {"days": 0, "tokens": 0, "cost": "about $0"}


# --- status

def test_status_summary_counts_insights(root, db, seeded_2026_10_23_subset, cfg):
    assert status_summary(db, root, cfg, now_ms=NOW)["insights"] == {"days_done": 0, "days_error": 0}
    generate_day(db, root, cfg, FakeProvider(), DAY, now_ms=NOW)
    db.set_insight_error(date(2026, 10, 22), provider="anthropic", model="m", prompt_version=1, generated_ms=0,
                         input_chars=0, error="x")
    s = status_summary(db, root, cfg, now_ms=NOW)
    assert s["insights"] == {"days_done": 1, "days_error": 1} and "pending_transcripts" in s


# --- the boundary

def test_insights_never_imports_playback_or_opens_audio():
    files = sorted(SRC.rglob("*.py"))
    assert files
    bad_import = re.compile(r"^\s*(from|import)\s+(lavalier\.playback|lavalier\.audio|subprocess)\b"
                            r"|^\s*from\s+lavalier\s+import\s+.*\b(playback|audio)\b", re.M)
    bad_open = re.compile(r"open\([^)]*audio/")
    for f in files:
        src = f.read_text()
        assert not bad_import.search(src), f
        assert not bad_open.search(src), f
        assert "paths.audio" not in src and ".audio /" not in src, f
