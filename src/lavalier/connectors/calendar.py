"""Calendar labels: name a conversation after the event it overlaps most.

Read-only through EventKit (pyobjc), behind CalendarSource so tests use a fake. EventKit and
Foundation are imported inside EventKitSource's methods only, never at module import, so neither the
test suite nor `process` loads pyobjc. EventKit names checked against pyobjc-framework-EventKit 12.2.2
on 2026-10-24.
"""

import logging
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional, Protocol

log = logging.getLogger(__name__)

AUTH = ("not-asked", "allowed", "denied", "restricted")

# EKAuthorizationStatus: NotDetermined 0, Restricted 1, Denied 2, Authorized/FullAccess 3, WriteOnly 4.
# Write-only access cannot read events, so for labelling it is as good as denied.
_STATUS = {0: "not-asked", 1: "restricted", 2: "denied", 3: "allowed", 4: "denied"}
_ENTITY_EVENT = 0  # EKEntityTypeEvent
ACCESS_TIMEOUT_S = 120


@dataclass(frozen=True)
class Calendar:
    identifier: str
    title: str
    colour: Optional[str]  # "#rrggbb", or None when EventKit gives none


@dataclass(frozen=True)
class Event:
    title: str
    start_ms: int
    end_ms: int
    all_day: bool
    calendar_id: str


class CalendarSource(Protocol):
    def authorization(self) -> str: ...

    def request_access(self) -> str:
        """Block until the system answers; return the new status."""
        ...

    def calendars(self) -> list[Calendar]: ...

    def events(self, day: date) -> list[Event]:
        """The day's events, local midnight to midnight."""
        ...


UNAVAILABLE = "unavailable"  # the authorization when EventKit cannot be loaded


class NoCalendar:
    """The source without EventKit: never allowed, so nothing is labelled; with the connector off, process
    still clears the labels through it."""

    def authorization(self) -> str:
        return UNAVAILABLE

    def request_access(self) -> str:
        return UNAVAILABLE

    def calendars(self) -> list[Calendar]:
        return []

    def events(self, day: date) -> list[Event]:
        return []


def process_source() -> "CalendarSource":
    """What a process labels from: the real calendars when pyobjc's EventKit loads, else NoCalendar. The
    import is heavy: never on the app's loop."""
    return EventKitSource() if event_kit_available() else NoCalendar()


def event_kit_available() -> bool:
    try:
        import EventKit  # noqa: F401
    except ImportError:
        return False
    return True


def _day_bounds_s(day: date) -> tuple[float, float]:
    start = datetime.combine(day, time())
    return start.timestamp(), datetime.combine(day + timedelta(days=1), time()).timestamp()


def _hex_colour(cal) -> Optional[str]:
    try:
        from AppKit import NSColorSpace
        c = cal.color().colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
        r, g, b = (max(0, min(255, round(x * 255))) for x in (c.redComponent(), c.greenComponent(), c.blueComponent()))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return None


class EventKitSource:
    """The real calendars on this Mac. Never constructed in tests."""

    def __init__(self):
        self._store = None

    def _event_store(self):
        if self._store is None:
            import EventKit
            self._store = EventKit.EKEventStore.alloc().init()
        return self._store

    def authorization(self) -> str:
        import EventKit
        status = EventKit.EKEventStore.authorizationStatusForEntityType_(_ENTITY_EVENT)
        return _STATUS.get(int(status), "denied")

    def request_access(self) -> str:
        done = threading.Event()

        def completion(granted, error):
            if error is not None:
                log.warning("calendar access request: %s", error)
            done.set()

        store = self._event_store()
        if hasattr(store, "requestFullAccessToEventsWithCompletion_"):  # macOS 14+
            store.requestFullAccessToEventsWithCompletion_(completion)
        else:
            store.requestAccessToEntityType_completion_(_ENTITY_EVENT, completion)
        if not done.wait(ACCESS_TIMEOUT_S):
            log.warning("calendar access request: no answer within %d s", ACCESS_TIMEOUT_S)
        # a store made before access was granted may go on seeing no calendars: the next read builds a new one
        self._store = None
        return self.authorization()

    def calendars(self) -> list[Calendar]:
        return [Calendar(identifier=str(c.calendarIdentifier()), title=str(c.title() or ""), colour=_hex_colour(c))
                for c in self._event_store().calendarsForEntityType_(_ENTITY_EVENT) or []]

    def events(self, day: date) -> list[Event]:
        from Foundation import NSDate
        start_s, end_s = _day_bounds_s(day)
        store = self._event_store()
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            NSDate.dateWithTimeIntervalSince1970_(start_s), NSDate.dateWithTimeIntervalSince1970_(end_s), None)
        out = []
        for e in store.eventsMatchingPredicate_(predicate) or []:
            cal = e.calendar()
            out.append(Event(
                title=str(e.title() or ""),
                start_ms=int(e.startDate().timeIntervalSince1970() * 1000),
                end_ms=int(e.endDate().timeIntervalSince1970() * 1000),
                all_day=bool(e.isAllDay()),
                calendar_id=str(cal.calendarIdentifier()) if cal is not None else "",
            ))
        return out


def chosen_calendar_ids(raw: str) -> set[str]:
    """`calendar_ids` as a set: separated by commas or lines; empty means every calendar."""
    return {p.strip() for p in re.split(r"[,\n]", raw) if p.strip()}


def pick_label(conv_start_ms: int, conv_end_ms: int, events: list[Event],
               calendar_ids: set[str]) -> Optional[str]:
    """The title of the timed event from a chosen calendar that overlaps the conversation most (ties go
    to the earlier event); None without overlap. An empty `calendar_ids` means every calendar."""
    best: Optional[tuple[int, int, str]] = None  # (-overlap, start, title): the smallest wins
    for e in events:
        if e.all_day or (calendar_ids and e.calendar_id not in calendar_ids):
            continue
        title = " ".join(e.title.split())
        overlap = min(conv_end_ms, e.end_ms) - max(conv_start_ms, e.start_ms)
        if not title or overlap <= 0:
            continue
        key = (-overlap, e.start_ms, title)
        if best is None or key[:2] < best[:2]:
            best = key
    return best[2] if best is not None else None


def label_day(db, cfg, source: CalendarSource, day: date) -> int:
    """Label the day's conversations from the calendar; return how many carry a label. With the connector
    off, the day's labels are cleared (the source is not read) and 0 is returned, so turning it off removes
    the names at the next process. With it on, nothing changes (0) unless access is allowed; a failing read
    leaves the labels as they were. Marks the day dirty when a label changed, so its file is rewritten."""
    if not cfg.calendar_enabled:
        _set_labels(db, day, lambda conv: None)
        return 0
    try:
        if source.authorization() != "allowed":
            return 0
        events = source.events(day)
    except Exception:
        log.exception("calendar labels for %s failed; labels left as they were", day)
        return 0
    chosen = chosen_calendar_ids(cfg.calendar_ids)
    return _set_labels(db, day, lambda conv: pick_label(conv.start_ms, conv.end_ms, events, chosen))


def _set_labels(db, day: date, label_of) -> int:
    """Give each of the day's conversations `label_of(conv)`; mark the day dirty when one changed. Returns
    how many carry a label."""
    labelled = 0
    changed = False
    for conv in db.conversations_for_day(day):
        label = label_of(conv)
        if label != conv.label:
            db.set_conversation_label(conv.conversation_id, label)
            changed = True
        labelled += label is not None
    if changed:
        db.mark_day_dirty(day)
    return labelled
