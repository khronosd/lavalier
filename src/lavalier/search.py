"""Full-text search over transcript segments: safe query shaping and the mapping from index rows to moments."""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from lavalier.db import Database
from lavalier.journal import segment_at_ms


@dataclass(frozen=True)
class Hit:
    day: date
    conversation_id: Optional[str]
    clip_id: str
    seq: int
    at_ms: int
    snippet: str


def _quote(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def fts_query(user_text: str) -> str:
    """Shape free text into an FTS5 expression that cannot raise: quoted phrases stay phrases, every other
    run of non-space characters becomes a quoted term (so AND, NOT, NEAR, *, col:x are plain words), all ANDed.
    An unterminated quote is dropped and the text after it read as ordinary words."""
    text = user_text.replace("\x00", "")
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == '"':
            end = text.find('"', i + 1)
            if end == -1:
                i += 1  # dangling quote: literal text, dropped
                continue
            phrase = text[i + 1:end].strip()
            if phrase:
                out.append(_quote(phrase))
            i = end + 1
        else:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            out.append(_quote(text[i:j]))
            i = j
    return " ".join(out)


def search(db: Database, user_text: str, *, limit: int = 50) -> list[Hit]:
    match = fts_query(user_text)
    if not match:
        return []
    convs: dict[date, list] = {}
    hits = []
    for r in db.search_segments(match, limit=limit):
        clip = db.clip(r["clip_id"])
        start_s = db.segment_start_s(r["clip_id"], r["seq"])
        if clip is None or start_s is None:
            continue
        at_ms = segment_at_ms(clip.first_ms, start_s)
        if clip.day not in convs:
            convs[clip.day] = db.conversations_for_day(clip.day)
        cid = next((c.conversation_id for c in convs[clip.day] if c.start_ms <= at_ms <= c.end_ms), None)
        hits.append(Hit(clip.day, cid, r["clip_id"], r["seq"], at_ms, r["snippet"]))
    return hits
