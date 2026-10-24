"""One day-view model, built from the database, that the Markdown file and the window both render."""

import dataclasses
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from lavalier.config import Config
from lavalier.db import Database
from lavalier.group import orphan_stars, press_times
from lavalier.models import ClipRecord
from lavalier.retention import deadline_ms

QUOTE_WINDOW_MS = 10_000
_HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Line:
    at_ms: int
    text: str
    clip_id: str
    seq: int  # segment index within its clip


@dataclass(frozen=True)
class StarView:
    at_ms: int
    conversation_id: Optional[str]
    quote: Optional[str]


@dataclass(frozen=True)
class ConversationView:
    conversation_id: str
    start_ms: int
    end_ms: int
    speech_ms: int
    star_ms: list[int]
    pinned: bool
    label: Optional[str]
    clip_ids: list[str]
    lines: list[Line]
    audio_available: bool


@dataclass(frozen=True)
class DayView:
    day: date
    speech_ms: int
    conversations: list[ConversationView]
    stars: list[StarView]
    noise_clips: int
    audio_until: Optional[date]
    audio_kept_for_good: bool
    pending_pages: Optional[int]


@dataclass(frozen=True)
class DaySummary:
    day: date
    speech_ms: int
    conversations: int
    stars: int
    noise_clips: int


def _lines(db: Database, clips: list[ClipRecord]) -> list[Line]:
    lines = []
    for c in clips:
        t = db.transcript(c.clip_id)
        if t is None:
            continue
        lines += [Line(c.first_ms + round(s.start_s * 1000), s.text.strip(), c.clip_id, i)
                  for i, s in enumerate(t.segments)]
    lines.sort(key=lambda ln: ln.at_ms)
    return lines


def _quote(star_ms: int, lines: list[Line]) -> Optional[str]:
    for ln in lines:
        if star_ms <= ln.at_ms <= star_ms + QUOTE_WINDOW_MS:
            return ln.text
    return None


def _audio_until(clips: list[ClipRecord], protected_ids: set[str], cfg: Config) -> Optional[date]:
    """Latest deletion date among unprotected clips (speech and noise) that still have audio."""
    deadlines = [d for c in clips if c.path and c.clip_id not in protected_ids
                 if (d := deadline_ms(c, cfg, protected=False)) is not None]
    return datetime.fromtimestamp(max(deadlines) / 1000).date() if deadlines else None


def _kept_for_good(clips: list[ClipRecord], protected_ids: set[str]) -> bool:
    return any(c.path and (c.clip_id in protected_ids or c.classification == "failed") for c in clips)


def _pending_pages(db: Database, now_ms: int) -> Optional[int]:
    latest = db.latest_device_status()
    if latest is None or now_ms - latest[0].read_at_ms >= _HOUR_MS:
        return None
    return latest[0].pages_waiting


def day_view(db: Database, day: date, cfg: Config, *, now_ms: int) -> DayView:
    clips = db.clips_for_day(day)
    by_id = {c.clip_id: c for c in clips}
    convs = db.conversations_for_day(day)

    protected_ids = {i for c in convs if c.star_ms or c.pinned for i in c.clip_ids}
    views, stars = [], []
    for conv in convs:
        members = [by_id[i] for i in conv.clip_ids if i in by_id]
        lines = _lines(db, members)
        views.append(ConversationView(
            conversation_id=conv.conversation_id, start_ms=conv.start_ms, end_ms=conv.end_ms,
            speech_ms=conv.speech_ms, star_ms=list(conv.star_ms), pinned=conv.pinned,
            label=conv.label, clip_ids=list(conv.clip_ids), lines=lines,
            audio_available=bool(members) and all(c.path for c in members)))
        stars += [StarView(ms, conv.conversation_id, _quote(ms, lines)) for ms in conv.star_ms]
    stars += [StarView(ms, None, None) for ms in orphan_stars(press_times(db, day), convs)]
    stars.sort(key=lambda s: s.at_ms)

    return DayView(
        day=day, speech_ms=sum(c.speech_ms for c in convs), conversations=views, stars=stars,
        noise_clips=sum(1 for c in clips if c.classification == "noise"),
        audio_until=_audio_until(clips, protected_ids, cfg),
        audio_kept_for_good=_kept_for_good(clips, protected_ids), pending_pages=_pending_pages(db, now_ms))


def days_index(db: Database, cfg: Config, *, now_ms: int) -> list[DaySummary]:
    """One summary per day with clips, newest first."""
    out = []
    for day in sorted(db.days_with_clips(), reverse=True):
        v = day_view(db, day, cfg, now_ms=now_ms)
        out.append(DaySummary(day, v.speech_ms, len(v.conversations), len(v.stars), v.noise_clips))
    return out


def all_stars(db: Database, cfg: Config) -> list[tuple[date, StarView]]:
    """Every star of every day, newest first."""
    out = []
    for day in sorted(db.days_with_clips(), reverse=True):
        out += [(day, s) for s in reversed(day_view(db, day, cfg, now_ms=0).stars)]
    return out


def to_json(obj: Any) -> Any:
    """Dataclasses (nested, in lists or tuples) to plain JSON-able values; dates as ISO strings."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return to_json(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {k: to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj
