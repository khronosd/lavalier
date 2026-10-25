import dataclasses
import logging
import subprocess
import sys
from datetime import date

import pytest

from conftest import T, _real_transcript, speech_transcript
from fake_calendar import FakeCalendarSource
from lavalier.config import Config
from lavalier.connectors.calendar import (
    AUTH, Calendar, Event, chosen_calendar_ids, event_kit_available, label_day, pick_label,
)
from lavalier.group import rebuild_day

DAY = date(2026, 10, 23)
ON = Config(calendar_enabled=True)


def ev(title, start, end, *, all_day=False, cal="work"):
    return Event(title=title, start_ms=start, end_ms=end, all_day=all_day, calendar_id=cal)


# pick_label

def test_no_overlap_is_no_label():
    events = [ev("Before", T(9, 0, 0), T(10, 0, 0)), ev("After", T(11, 0, 0), T(12, 0, 0))]
    assert pick_label(T(10, 0, 0), T(11, 0, 0), events, set()) is None  # touching edges do not overlap
    assert pick_label(T(10, 0, 0), T(11, 0, 0), [], set()) is None


def test_all_day_events_are_ignored():
    events = [ev("Holiday", T(0, 0, 0), T(23, 59, 59), all_day=True), ev("Standup", T(10, 50, 0), T(11, 30, 0))]
    assert pick_label(T(10, 0, 0), T(11, 0, 0), events, set()) == "Standup"
    assert pick_label(T(10, 0, 0), T(10, 30, 0), events[:1], set()) is None


def test_the_larger_overlap_wins():
    events = [ev("Short", T(9, 0, 0), T(10, 10, 0)), ev("Long", T(10, 20, 0), T(12, 0, 0))]
    assert pick_label(T(10, 0, 0), T(11, 0, 0), events, set()) == "Long"


def test_a_tie_goes_to_the_earlier_event():
    events = [ev("Later", T(10, 50, 0), T(12, 0, 0)), ev("Earlier", T(9, 0, 0), T(10, 10, 0))]
    assert pick_label(T(10, 0, 0), T(11, 0, 0), events, set()) == "Earlier"


def test_a_calendar_not_chosen_is_ignored_and_an_empty_choice_means_all():
    events = [ev("Private", T(10, 0, 0), T(11, 0, 0), cal="home"), ev("Work", T(10, 40, 0), T(11, 0, 0))]
    assert pick_label(T(10, 0, 0), T(11, 0, 0), events, {"work"}) == "Work"
    assert pick_label(T(10, 0, 0), T(11, 0, 0), events, {"other"}) is None
    assert pick_label(T(10, 0, 0), T(11, 0, 0), events, set()) == "Private"


def test_the_title_is_one_line_and_an_empty_title_is_skipped():
    events = [ev("  \n ", T(10, 0, 0), T(11, 0, 0)), ev("  Weekly\n  sync ", T(10, 30, 0), T(11, 0, 0))]
    assert pick_label(T(10, 0, 0), T(11, 0, 0), events, set()) == "Weekly sync"


def test_chosen_calendar_ids_split_on_commas_and_lines():
    assert chosen_calendar_ids("a, b\nc,,\n") == {"a", "b", "c"}
    assert chosen_calendar_ids("") == set()


# label_day

@pytest.fixture
def two_conversations(db, clip):
    """Two speech conversations on 2026-10-23: 10:00-10:05 and 14:00-14:05."""
    ids = []
    for h in (10, 14):
        c = clip(T(h, 0, 0), T(h, 5, 0))
        db.add_clip(dataclasses.replace(c, classification=None, transcribed_at=None))
        db.set_transcript(c.clip_id, _real_transcript(), "speech", T(h, 6, 0))
    convs = rebuild_day(db, DAY, Config())
    db.mark_day_clean(DAY)
    return [c.conversation_id for c in convs]


def _labels(db):
    return [c.label for c in db.conversations_for_day(DAY)]


def test_label_day_names_each_conversation_after_its_event(db, two_conversations):
    src = FakeCalendarSource(events={DAY: [ev("Standup", T(9, 55, 0), T(10, 15, 0))]})
    assert label_day(db, ON, src, DAY) == 1
    assert _labels(db) == ["Standup", None]
    assert db.days_dirty() == [DAY]  # the day file must be rewritten
    assert src.events_calls == [DAY]  # fetched once for the whole day


def test_relabelling_with_nothing_changed_leaves_the_day_clean(db, two_conversations):
    src = FakeCalendarSource(events={DAY: [ev("Standup", T(9, 55, 0), T(10, 15, 0))]})
    label_day(db, ON, src, DAY)
    db.mark_day_clean(DAY)
    assert label_day(db, ON, src, DAY) == 1
    assert db.days_dirty() == []


def test_relabelling_replaces_an_old_label_and_clears_it_when_the_event_is_gone(db, two_conversations):
    src = FakeCalendarSource(events={DAY: [ev("Standup", T(9, 55, 0), T(10, 15, 0)),
                                           ev("Review", T(14, 0, 0), T(15, 0, 0))]})
    assert label_day(db, ON, src, DAY) == 2
    src.events_by_day[DAY] = [ev("Planning", T(9, 0, 0), T(10, 3, 0))]  # Standup moved, Review deleted
    db.mark_day_clean(DAY)
    assert label_day(db, ON, src, DAY) == 1
    assert _labels(db) == ["Planning", None]
    assert db.days_dirty() == [DAY]


@pytest.mark.parametrize("status", ["not-asked", "denied", "restricted"])
def test_labelling_is_skipped_without_authorisation(db, two_conversations, status):
    db.set_conversation_label(two_conversations[0], "Kept")
    src = FakeCalendarSource(authorization=status, events={DAY: [ev("Standup", T(9, 55, 0), T(10, 15, 0))]})
    assert label_day(db, ON, src, DAY) == 0
    assert _labels(db) == ["Kept", None] and src.events_calls == [] and db.days_dirty() == []


def test_labelling_is_skipped_when_the_connector_is_off(db, two_conversations):
    src = FakeCalendarSource(events={DAY: [ev("Standup", T(9, 55, 0), T(10, 15, 0))]})
    assert label_day(db, Config(), src, DAY) == 0
    assert _labels(db) == [None, None] and src.events_calls == []


def test_only_the_chosen_calendars_label(db, two_conversations):
    src = FakeCalendarSource(events={DAY: [ev("Dentist", T(9, 55, 0), T(10, 15, 0), cal="home"),
                                           ev("Review", T(14, 0, 0), T(15, 0, 0), cal="work")]})
    assert label_day(db, Config(calendar_enabled=True, calendar_ids="work"), src, DAY) == 1
    assert _labels(db) == [None, "Review"]


def test_a_failing_calendar_read_is_logged_and_leaves_labels_alone(db, two_conversations, caplog):
    db.set_conversation_label(two_conversations[0], "Kept")
    src = FakeCalendarSource(events_error=RuntimeError("store gone"))
    with caplog.at_level(logging.ERROR, logger="lavalier.connectors.calendar"):
        assert label_day(db, ON, src, DAY) == 0
    assert _labels(db) == ["Kept", None] and "store gone" in caplog.text


def test_a_day_without_conversations_labels_nothing(db):
    src = FakeCalendarSource(events={DAY: [ev("Standup", T(9, 55, 0), T(10, 15, 0))]})
    assert label_day(db, ON, src, DAY) == 0 and db.days_dirty() == []


# the fake and the real source

def test_the_fake_request_access_flips_to_its_scripted_status():
    src = FakeCalendarSource(authorization="not-asked", grant="denied")
    assert src.request_access() == "denied" and src.authorization() == "denied" and src.access_requests == 1
    assert set(AUTH) == {"not-asked", "allowed", "denied", "restricted"}
    assert FakeCalendarSource(calendars=[Calendar("a", "Work", None)]).calendars()[0].title == "Work"


def test_event_kit_available_is_false_when_the_import_fails(monkeypatch):
    monkeypatch.setitem(sys.modules, "EventKit", None)  # makes `import EventKit` raise ImportError
    assert event_kit_available() is False


def test_importing_the_connector_and_the_pipeline_loads_no_pyobjc():
    code = ("import sys, lavalier.connectors.calendar, lavalier.pipeline; "
            "bad = [m for m in ('EventKit', 'objc', 'Foundation') if m in sys.modules]; "
            "assert not bad, bad")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_the_status_map_covers_every_eventkit_status():
    from lavalier.connectors.calendar import _STATUS
    assert _STATUS == {0: "not-asked", 1: "restricted", 2: "denied", 3: "allowed", 4: "denied"}


# --- R7: turning the calendar off removes the names at the next process

@pytest.fixture
def labelled_day(db, clip):
    c = clip(T(10, 0, 0), T(10, 5, 0))
    db.add_clip(dataclasses.replace(c, classification=None, transcribed_at=None))
    db.set_transcript(c.clip_id, _real_transcript(), "speech", T(10, 6, 0))
    convs = rebuild_day(db, DAY, Config())
    db.set_conversation_label(convs[0].conversation_id, "Standup")
    db.mark_day_clean(DAY)
    return convs[0].conversation_id


class _Untouchable:
    def __getattr__(self, name):
        raise AssertionError(f"the calendar was read: {name}")


def test_label_day_with_the_connector_off_clears_the_labels(db, labelled_day):
    assert label_day(db, Config(), _Untouchable(), DAY) == 0
    assert [c.label for c in db.conversations_for_day(DAY)] == [None]
    assert db.days_dirty() == [DAY]
    db.mark_day_clean(DAY)
    assert label_day(db, Config(), _Untouchable(), DAY) == 0
    assert db.days_dirty() == []                       # nothing changed the second time


def test_a_process_with_the_calendar_off_removes_the_names(root, db, labelled_day):
    from lavalier.pipeline import process
    from lavalier.transcribe import FakeTranscriber
    db.mark_day_dirty(DAY)
    process(db, root, Config(), FakeTranscriber({}, default=speech_transcript()), now_ms=T(23, 30, 0),
            calendar=_Untouchable())
    assert [c.label for c in db.conversations_for_day(DAY)] == [None]
