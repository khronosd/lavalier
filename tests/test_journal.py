import dataclasses
import json
from datetime import date
from pathlib import Path

import pytest

from conftest import T
from lavalier.dayfile import render_day
from lavalier.journal import all_stars, day_view, days_index, to_json

NOW = T(23, 30, 0)
DAY = date(2026, 10, 23)


@pytest.fixture
def db_with_fixture_day(db, seeded_2026_10_23_subset):
    return db


@pytest.fixture
def db_two_days(db, seeded_2026_10_23_subset, clip_record):
    first = int(T(12, 0, 0) + 86_400_000)
    c = dataclasses.replace(clip_record, clip_id="clip_20261024T190000.000Z", day=date(2026, 10, 24),
                            path="audio/2026-10-24/clip_20261024T190000.000Z.opus",
                            first_ms=first, last_ms=first + 16000, classification=None, transcribed_at=None)
    db.add_clip(c)
    from conftest import _real_transcript
    db.set_transcript(c.clip_id, _real_transcript(), "speech", T(23, 0, 0))
    return db


def test_day_view_matches_the_fixture_day(db_with_fixture_day, cfg):
    v = day_view(db_with_fixture_day, DAY, cfg, now_ms=NOW)
    assert v.speech_ms > 0 and len(v.conversations) == 1 and len(v.stars) == 2 and v.noise_clips == 2
    c = v.conversations[0]
    assert c.lines[0].text == "test test test one two three" and c.lines[0].at_ms < c.lines[1].at_ms
    assert [ln.seq for ln in c.lines] == [0, 1]
    assert all(s.conversation_id == c.conversation_id for s in v.stars) and v.stars[0].quote == "test test test one two three"


def test_render_day_is_unchanged_by_the_refactor(db_with_fixture_day, cfg):
    assert render_day(db_with_fixture_day, DAY, cfg, now_ms=NOW) == (
        Path(__file__).parent / "golden" / "2026-10-23.md").read_text()


def test_days_index_is_newest_first_with_counts(db_two_days, cfg):
    idx = days_index(db_two_days, cfg, now_ms=NOW)
    assert [d.day for d in idx] == [date(2026, 10, 24), date(2026, 10, 23)] and idx[1].stars == 2


def test_all_stars_newest_first(db_two_days, cfg):
    stars = all_stars(db_two_days, cfg)
    assert [d for d, _ in stars] == [DAY, DAY] and stars[0][1].at_ms > stars[1][1].at_ms


def test_audio_availability_follows_the_files(db_with_fixture_day, cfg):
    v = day_view(db_with_fixture_day, DAY, cfg, now_ms=NOW)
    assert v.conversations[0].audio_available and v.audio_until is not None
    assert v.audio_kept_for_good  # the starred conversation's clip is protected
    for c in db_with_fixture_day.clips_for_day(DAY):
        db_with_fixture_day.clear_clip_path(c.clip_id)
    v2 = day_view(db_with_fixture_day, DAY, cfg, now_ms=NOW)
    assert not v2.conversations[0].audio_available
    assert v2.audio_until is None and not v2.audio_kept_for_good
    assert to_json(v2)["audio_kept_for_good"] is False


def test_pending_pages_only_when_the_status_is_fresh(db_with_fixture_day, cfg):
    from lavalier.models import DeviceSnapshot
    assert day_view(db_with_fixture_day, DAY, cfg, now_ms=NOW).pending_pages is None
    snap = DeviceSnapshot(NOW - 60_000, True, "LISTENING", 10, 19, 90, -10, "USB_DISCONNECTED", "1.1.3", 7)
    db_with_fixture_day.record_device_status(snap, source="test", charger_signal="none")
    assert day_view(db_with_fixture_day, DAY, cfg, now_ms=NOW).pending_pages == 10
    assert day_view(db_with_fixture_day, DAY, cfg, now_ms=NOW + 3_600_000).pending_pages is None


def test_to_json_serialises_dates_and_nested_dataclasses(db_with_fixture_day, cfg):
    j = to_json(day_view(db_with_fixture_day, DAY, cfg, now_ms=NOW))
    assert j["day"] == "2026-10-23" and j["conversations"][0]["lines"][0]["clip_id"].startswith("clip_")
    json.dumps(j)
    json.dumps(to_json(days_index(db_with_fixture_day, cfg, now_ms=NOW)))
