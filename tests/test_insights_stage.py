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
    DAY_COMPLETE_HOUR, NO_SPEECH, ask_day, day_is_complete, due_days, generate_day,
)
from lavalier.models import Transcript
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
    from lavalier.dayfile import write_dirty_days
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


def test_a_day_without_speech_is_not_sent_and_stores_nothing(root, db, cfg, clip_record):
    db.add_event(_press(7000, T(22, 50, 0)))  # a star alone: no clips, no speech
    rebuild_day(db, DAY, cfg)
    p = FakeProvider()
    r = generate_day(db, root, cfg, p, DAY, now_ms=T(22, 55, 0))
    assert r.state == "error" and r.error == NO_SPEECH and r.insight is None and p.calls == []
    assert (r.provider, r.model, r.generated_ms) == ("anthropic", "claude-opus-5-5", T(22, 55, 0))
    assert db.insight(DAY) is None and not (root.days / "2026-10-23.md").exists()
    # speech arrives later; once the day is complete the automatic send still picks it up
    _speech_day(db, clip_record, DAY, 0)
    _drained(db, T_next(4, 0, 1))
    assert due_days(db, _cfg(cfg), now_ms=T_next(4, 0, 1), enabled_at_ms=0) == [DAY]


def test_a_failed_regenerate_keeps_the_done_row_and_the_day_file(root, db, seeded_2026_10_23_subset, cfg):
    done = generate_day(db, root, cfg, FakeProvider(), DAY, now_ms=NOW)
    f = root.days / "2026-10-23.md"
    before, mtime = f.read_text(), f.stat().st_mtime_ns
    for p in (FakeProvider(error="timed out"), FakeProvider(reply={"summary": "x"}),
              FakeProvider(exc=KeychainError("The Keychain refused: locked"))):
        r = generate_day(db, root, cfg, p, DAY, now_ms=NOW + 60_000)
        assert r.state == "error" and r.error and r.insight is None and r.generated_ms == NOW + 60_000
        assert db.insight(DAY) == done and db.insight(DAY).state == "done"
        assert f.read_text() == before and f.stat().st_mtime_ns == mtime


def test_a_failed_generate_replaces_an_earlier_error(root, db, seeded_2026_10_23_subset, cfg):
    generate_day(db, root, cfg, FakeProvider(error="first"), DAY, now_ms=NOW)
    generate_day(db, root, cfg, FakeProvider(error="second"), DAY, now_ms=NOW + 1)
    assert db.insight(DAY).error == "second"


def test_the_insight_and_the_dirty_mark_land_together(root, db, seeded_2026_10_23_subset, cfg, monkeypatch):
    def boom(day):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "mark_day_dirty", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        generate_day(db, root, cfg, FakeProvider(), DAY, now_ms=NOW)
    assert db.insight(DAY) is None and not (root.days / "2026-10-23.md").exists()


def test_a_truncated_day_is_stored_and_noted_in_the_day_file(root, db, seeded_2026_10_23_subset, cfg, monkeypatch):
    real = stage.day_text
    monkeypatch.setattr(stage, "day_text",
                        lambda db, day, cfg, *, now_ms: dataclasses.replace(real(db, day, cfg, now_ms=now_ms), truncated=True))
    r = generate_day(db, root, cfg, FakeProvider(), DAY, now_ms=NOW)
    assert r.truncated and db.insight(DAY).truncated
    out = (root.days / "2026-10-23.md").read_text()
    assert "_Insights by claude-opus-5-5 (Anthropic) at 04:12 (the earlier part of the day was left out)._" in out
    r = generate_day(db, root, cfg, FakeProvider(error="timed out"), DAY, now_ms=NOW + 1)
    assert r.state == "error" and r.truncated  # the error record says the text was cut too


def test_an_untruncated_day_is_not_noted(root, db, seeded_2026_10_23_subset, cfg):
    r = generate_day(db, root, cfg, FakeProvider(), DAY, now_ms=NOW)
    assert not r.truncated and "left out" not in (root.days / "2026-10-23.md").read_text()


def test_importing_the_stage_leaves_transcription_unloaded():
    import subprocess
    import sys
    # lavalier.playback, lavalier.audio and subprocess do load: journal -> retention -> playback -> audio
    # (subprocess). The stage itself never imports them (the source scan below holds that).
    watch = ["lavalier.transcribe", "lavalier.pipeline", "lavalier.capture", "lavalier.sync"]
    code = ("import lavalier.insights.stage, sys; "
            f"print(sorted(m for m in sys.modules if m in {set(watch)!r}))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


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


def _drained(db, ended_ms: int) -> None:
    """A successful drain that ended at `ended_ms`."""
    run = db.start_sync_run(ended_ms - 1000)
    db.finish_sync_run(run, ended_ms=ended_ms, outcome="drained", reason="charger", pages=10, messages=10,
                       capture_id=None, muted_by=None, unmute="", error=None)


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
    _drained(db, T_next(2, 0))
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=enabled) == [d18, d19, d22]
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=enabled + 1) == [d19, d22]
    assert due_days(db, _cfg(cfg), now_ms=T_next(4, 0, 1), enabled_at_ms=enabled) == [d18, d19, d22]
    _drained(db, T_next(4, 0, 1))
    assert due_days(db, _cfg(cfg), now_ms=T_next(4, 0, 1), enabled_at_ms=enabled) == [d18, d19, d22, DAY]


def test_due_days_ignores_days_without_speech(db, cfg, clip_record):
    c = dataclasses.replace(clip_record, clip_id="clip_noise", day=date(2026, 10, 20), first_ms=at(date(2026, 10, 20)),
                            last_ms=at(date(2026, 10, 20)) + 5000, classification="noise")
    db.add_clip(c)
    assert due_days(db, _cfg(cfg), now_ms=T_next(12, 0), enabled_at_ms=0) == []


def test_due_days_is_empty_when_auto_is_off(db, cfg, five_speech_days):
    now = T_next(12, 0)
    _drained(db, now)
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=0) == five_speech_days
    assert due_days(db, _cfg(cfg, insights_auto=False), now_ms=now, enabled_at_ms=0) == []
    assert due_days(db, cfg, now_ms=now, enabled_at_ms=0) == []  # no provider chosen
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=None) == []


# --- ask_day

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


def test_the_window_alone_estimates_a_range():
    # the range estimate is computed by the window (insights.ts rangeEstimate); the stage keeps no copy
    assert not hasattr(stage, "estimate") and not hasattr(stage, "_money")


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


# --- final fix wave: a day is due only once its audio is in (R21)

def test_a_complete_day_is_due_only_after_a_drain_that_ended_after_it_completed(db, cfg, clip_record):
    _speech_day(db, clip_record, DAY, 0)
    now = T_next(9, 0)
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=0) == []           # never drained
    _drained(db, T_next(3, 59))                       # the evening may still be on the pendant
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=0) == []
    _drained(db, T_next(8, 30))
    assert due_days(db, _cfg(cfg), now_ms=now, enabled_at_ms=0) == [DAY]


def test_a_day_with_a_clip_waiting_for_its_transcript_is_not_due(db, cfg, clip_record):
    _speech_day(db, clip_record, DAY, 0)
    _drained(db, T_next(8, 30))
    pending = dataclasses.replace(clip_record, clip_id="clip_pending", first_ms=at(DAY, 21), last_ms=at(DAY, 21) + 9000,
                                  classification=None, transcribed_at=None)
    db.add_clip(pending)
    assert db.days_needing_transcript() == {DAY}
    assert due_days(db, _cfg(cfg), now_ms=T_next(9, 0), enabled_at_ms=0) == []
    db.set_transcript("clip_pending", Transcript("", "en", cfg.whisper_model, []), "noise", T_next(9, 1))
    assert due_days(db, _cfg(cfg), now_ms=T_next(9, 2), enabled_at_ms=0) == [DAY]


def test_importing_the_pipeline_and_writing_insights_never_loads_keyring_or_the_adapters():
    import subprocess
    import sys
    code = (
        "import lavalier.pipeline, sys\n"
        "from datetime import date\n"
        "from lavalier import dayfile\n"
        "from lavalier.db import InsightRecord\n"
        "from lavalier.insights.schema import Insight\n"
        "rec = InsightRecord(date(2026, 10, 23), 'done', 'openai', 'm', 1, 0, 1, Insight('s', [], [], []), None)\n"
        "assert 'OpenAI' in ''.join(dayfile._insights(rec))\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('keyring', 'anthropic', 'openai')"
        " or m == 'google.genai' or m.startswith(('google.genai.', 'lavalier.insights.registry', 'lavalier.insights.keys', 'lavalier.insights.providers'))))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


def test_an_endpoint_run_is_stored_under_the_endpoint(root, db, seeded_2026_10_23_subset, cfg):
    p = FakeProvider(name="openai")
    p.base_url = "https://llm.example.net/v1"
    assert generate_day(db, root, cfg, p, DAY, now_ms=NOW).provider == "openai@llm.example.net"
    p.error = "rate limited"
    assert generate_day(db, root, cfg, p, DAY, now_ms=NOW).provider == "openai@llm.example.net"
    assert generate_day(db, root, cfg, FakeProvider(name="openai"), DAY, now_ms=NOW).provider == "openai"
