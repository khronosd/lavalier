"""The day's text as the model reads it, the prompts around it, and moment resolution."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from lavalier.config import Config
from lavalier.dayfile import render_conversation
from lavalier.db import Database
from lavalier.journal import DayView, day_view

MAX_CHARS = 400_000  # about 100k tokens; longer days are cut from the front
OMITTED = "[earlier part of the day omitted]\n"
MOMENT_WINDOW_MS = 60_000

SYSTEM_PROMPT = (
    "You read one day of a person's own transcribed conversations, recorded by a microphone they wear. "
    "Lines carry the time of day as [HH:MM:SS]; a line with ★ marks a moment the person starred. "
    "Write for that person, in plain language, in their own words where you can. "
    "Never invent names, events or decisions that are not in the text. "
    "Keep the summary to one short paragraph. "
    "A follow-up is something the person said they would do, decide, or look into; "
    "give each one the time of the line it comes from. "
    "People are names that appear in the text, as written. "
    "Topics are two to four words each. "
    "Answer only from the text; when the text does not say, say so."
)

_SUMMARIZE = (
    "Summarise this day. Reply with JSON: summary (one short paragraph), follow_ups (each with text and the time "
    "[HH:MM:SS] of the line it comes from), people (names as written in the text), topics (two to four words each)."
)
_ASK = "Answer the question from this day's text only. If the text does not say, say so."


@dataclass(frozen=True)
class DayText:
    day: date
    text: str
    chars: int
    truncated: bool
    day_start_ms: int
    has_speech: bool


def _cut_front(text: str) -> str:
    """Keep the last MAX_CHARS characters, starting at a line boundary, behind the omitted note."""
    tail = text[-MAX_CHARS:]
    if text[-MAX_CHARS - 1] != "\n":
        tail = tail.partition("\n")[2] or tail  # no line boundary in the kept text: keep the raw tail
    return OMITTED + tail


def day_text(db: Database, day: date, cfg: Config, *, now_ms: int) -> DayText:
    view = day_view(db, day, cfg, now_ms=now_ms)
    text = "\n".join(render_conversation(c, anchor=False) for c in view.conversations)
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = _cut_front(text)
    has_speech = any(c.lines for c in view.conversations)
    start = int(datetime.combine(day, datetime.min.time()).timestamp() * 1000)
    return DayText(day, text, len(text), truncated, start, has_speech)


def estimate_tokens(chars: int) -> int:
    return chars // 4


def summarize_messages(dt: DayText) -> list[dict]:
    return [{"role": "user", "content": f"{_SUMMARIZE}\n\n{dt.text}"}]


def ask_messages(dt: DayText, question: str) -> list[dict]:
    return [{"role": "user", "content": f"{_ASK}\n\nQuestion: {question}\n\n{dt.text}"}]


def resolve_moment(view: DayView, at_ms: int) -> Optional[str]:
    """The id "<clip_id>-<seq>" of the last line at or before at_ms and within a minute of it, compared in
    whole seconds: the model reads [HH:MM:SS], so a line at :13.045 cited as :13 is that line."""
    at_s, window_s = at_ms // 1000, MOMENT_WINDOW_MS // 1000
    found = None
    for conv in view.conversations:
        for line in conv.lines:
            line_s = line.at_ms // 1000
            if line_s <= at_s and at_s - line_s <= window_s:
                found = line
    return f"{found.clip_id}-{found.seq}" if found else None
