"""A scripted CalendarSource: no EventKit, no permission prompt."""

from datetime import date
from typing import Optional

from lavalier.connectors.calendar import Calendar, Event


class FakeCalendarSource:
    def __init__(self, authorization: str = "allowed", calendars: Optional[list[Calendar]] = None,
                 events: Optional[dict[date, list[Event]]] = None, *, grant: str = "allowed",
                 events_error: Optional[Exception] = None):
        self.status = authorization
        self._calendars = list(calendars or [])
        self.events_by_day = dict(events or {})
        self.grant = grant  # the status request_access flips to
        self.events_error = events_error  # raised from events() when set
        self.events_calls: list[date] = []
        self.access_requests = 0

    def authorization(self) -> str:
        return self.status

    def request_access(self) -> str:
        self.access_requests += 1
        self.status = self.grant
        return self.status

    def calendars(self) -> list[Calendar]:
        return list(self._calendars)

    def events(self, day: date) -> list[Event]:
        self.events_calls.append(day)
        if self.events_error is not None:
            raise self.events_error
        return list(self.events_by_day.get(day, []))
