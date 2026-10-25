"""Retrieval for a question across days: the question's words as an FTS5 query over every day's lines, the
best hits with the lines around them inside their conversation, capped and laid out newest day first with
the day and the time on every line, so the model answers from the moments and the window can link back
to them. Deterministic and free: no model call picks the terms."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from lavalier.config import Config
from lavalier.db import Database
from lavalier.journal import ConversationView, Line, day_view
from lavalier.search import _quote

# Function words and the words of a question that are never in the answer; everything else is a term.
STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below between both but by
can could did do does doing done down during each either few for from further had has have having he her here hers
herself him himself his how i if in into is it its itself just let me mine more most my myself no nor not now of off
on once only or other our ours out over own same she should so some such than that the their theirs them then there
these they this those through to too under until up very was we were what when where which while who whom why will
with would you your yours yourself ask asked tell told say said says talk talked speak spoke spoken mention mentioned
remember recall anything something everything nothing someone anyone everyone thing things time times
yesterday today tomorrow tonight week weeks month months year years ago last next earlier later ever never
""".split())
MIN_TERM = 3
HIT_LIMIT = 40
CONTEXT_LINES = 4
MAX_CHARS = 60_000

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def question_terms(question: str) -> list[str]:
    """The words worth searching for, lower-cased, in the order asked, each once: three letters or more
    and not a function word."""
    seen: set[str] = set()
    out: list[str] = []
    for w in _WORD.findall(question.lower()):
        if len(w) < MIN_TERM or w in STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def fts_or_query(terms: list[str]) -> str:
    """Each term as a quoted prefix ("decide"* reaches "decided"), all ORed; "" with no terms."""
    return " OR ".join(f"{_quote(t)}*" for t in terms)


@dataclass(frozen=True)
class Passage:
    """A run of consecutive lines of one conversation around one or more hits."""
    day: date
    conversation_id: str
    label: Optional[str]
    start_ms: int
    end_ms: int
    lines: tuple[Line, ...]
    hits: tuple[str, ...]       # the line ids ("<clip_id>-<seq>") the search found in it
    first: int                  # index of the first line within the conversation
    last: int                   # index of the last line within the conversation (inclusive)
    total: int                  # how many lines the conversation has


def _hms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


def _hm(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M")


def _sorted_lines(conv: ConversationView) -> list[Line]:
    return sorted(conv.lines, key=lambda ln: (ln.at_ms, ln.seq))


def gather(db: Database, cfg: Config, terms: list[str], *, now_ms: int, hit_limit: int = HIT_LIMIT,
           context: int = CONTEXT_LINES, max_chars: int = MAX_CHARS) -> list[Passage]:
    """The passages for these terms: the best `hit_limit` hits, each with `context` lines either side inside
    its conversation, overlapping windows merged, kept by relevance until `max_chars`, returned newest day
    first and in conversation order."""
    match = fts_or_query(terms)
    if not match:
        return []
    views = {}
    # (day, conversation) -> the hit indices in rank order; the first key seen is the most relevant
    by_conv: dict[tuple[date, str], list[int]] = {}
    for r in db.search_segments(match, limit=hit_limit):
        clip = db.clip(r["clip_id"])
        if clip is None:
            continue
        if clip.day not in views:
            views[clip.day] = day_view(db, clip.day, cfg, now_ms=now_ms)
        for conv in views[clip.day].conversations:
            lines = _sorted_lines(conv)
            idx = next((i for i, ln in enumerate(lines) if ln.clip_id == r["clip_id"] and ln.seq == r["seq"]), None)
            if idx is not None:
                by_conv.setdefault((clip.day, conv.conversation_id), []).append(idx)
                break
    passages: list[Passage] = []
    for (day, cid), idxs in by_conv.items():
        conv = next(c for c in views[day].conversations if c.conversation_id == cid)
        lines = _sorted_lines(conv)
        windows: list[list[int]] = []
        for i in sorted(set(idxs)):
            lo, hi = max(0, i - context), min(len(lines) - 1, i + context)
            if windows and lo <= windows[-1][1] + 1:
                windows[-1][1] = max(windows[-1][1], hi)
            else:
                windows.append([lo, hi])
        hit_ids = {f"{lines[i].clip_id}-{lines[i].seq}" for i in idxs}
        for lo, hi in windows:
            run = tuple(lines[lo:hi + 1])
            passages.append(Passage(day, cid, conv.label, run[0].at_ms, run[-1].at_ms, run,
                                    tuple(f"{ln.clip_id}-{ln.seq}" for ln in run if f"{ln.clip_id}-{ln.seq}" in hit_ids),
                                    lo, hi, len(lines)))
    kept: list[Passage] = []
    chars = 0
    for p in passages:  # relevance order: the conversations as their best hit ranked
        size = sum(len(ln.text) + 12 for ln in p.lines)
        if kept and chars + size > max_chars:
            break
        kept.append(p)
        chars += size
    return sorted(kept, key=lambda p: (-p.day.toordinal(), p.start_ms))


def day_heading(day: date) -> str:
    return f"{day.strftime('%A')}, {day.day} {day.strftime('%B %Y')}"


def render(passages: list[Passage]) -> str:
    """The passages as the model reads them: a heading per day, one per conversation, every line with its
    time, and […] where a window does not reach the conversation's ends."""
    out: list[str] = []
    current: Optional[date] = None
    for p in passages:
        if p.day != current:
            out.append(f"# {day_heading(p.day)}")
            current = p.day
        head = f"## {_hm(p.start_ms)} to {_hm(p.end_ms)}"
        out.append(f"{head} · {p.label}" if p.label else head)
        if p.first > 0:
            out.append("[…]")
        out += [f"[{_hms(ln.at_ms)}] {ln.text}" for ln in p.lines]
        if p.last < p.total - 1:
            out.append("[…]")
    return "\n".join(out) + ("\n" if out else "")


def sources(passages: list[Passage]) -> list[dict]:
    """Where the answer came from, one per passage, for the window to link: the first hit line."""
    out = []
    for p in passages:
        hit = p.hits[0] if p.hits else f"{p.lines[0].clip_id}-{p.lines[0].seq}"
        line = next(ln for ln in p.lines if f"{ln.clip_id}-{ln.seq}" == hit)
        out.append({"day": p.day.isoformat(), "conversation_id": p.conversation_id, "line_id": hit, "at_ms": line.at_ms})
    return out
