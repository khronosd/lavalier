"""A day as Notion blocks, with a stable plain text and hash of what the connector would read back."""

import hashlib
from datetime import date
from typing import Optional

from lavalier.dayfile import conversation_lines, heading_text, hm, hms, one_line
from lavalier.db import InsightRecord
from lavalier.insights.names import display
from lavalier.journal import ConversationView, DayView

OWNED_MARKER = "Written by lavalier. Edits inside this block are overwritten; add your notes outside it."
RUN_CHARS = 2000  # Notion's limit for one rich_text content
MAX_RUNS = 100    # ... and for the rich_text elements of one block
BATCH = 100       # children per append request
BATCH_BYTES = 400_000   # ... and at most this much JSON (Notion caps a request's payload at 500 kB)
CUT = "[… cut]"


def page_title(day: date) -> str:
    return day.isoformat()


def page_properties(view: DayView) -> dict:
    return {"Date": {"date": {"start": view.day.isoformat()}},
            "Speech (min)": {"number": round(view.speech_ms / 60000)},
            "Conversations": {"number": len(view.conversations)},
            "Stars": {"number": len(view.stars)}}


def property_schema() -> dict:
    return {"Date": {"date": {}},
            "Speech (min)": {"number": {"format": "number"}},
            "Conversations": {"number": {"format": "number"}},
            "Stars": {"number": {"format": "number"}}}


def split_runs(text: str) -> list[str]:
    """Cut `text` into runs of at most RUN_CHARS at line boundaries (a longer single line is cut hard); every
    run that ends at a line boundary keeps its "\\n", so the runs joined with "" are the text. At most MAX_RUNS;
    when more would be needed the last kept run becomes "[… cut]"."""
    lines = text.split("\n")
    pieces = [ln + "\n" for ln in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    runs: list[str] = []
    cur = ""
    for piece in pieces:
        while len(piece) > RUN_CHARS:
            if cur:
                runs.append(cur)
                cur = ""
            runs.append(piece[:RUN_CHARS])
            piece = piece[RUN_CHARS:]
        if len(cur) + len(piece) > RUN_CHARS:
            runs.append(cur)
            cur = ""
        cur += piece
    if cur:
        runs.append(cur)
    if len(runs) > MAX_RUNS:
        runs = runs[:MAX_RUNS - 1] + [CUT]
    return runs


def _runs(texts: list[str]) -> list[dict]:
    return [{"type": "text", "text": {"content": t}} for t in texts]


def _block(kind: str, text: str) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": _runs(split_runs(text))}}


def owned_block(children: list[dict]) -> dict:
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": _runs([OWNED_MARKER]), "icon": {"type": "emoji", "emoji": "🎙"},
                        "children": children}}


def _starred(view: DayView) -> list[dict]:
    out = [_block("heading_3", "Starred")]
    for s in view.stars:
        out.append(_block("bulleted_list_item", f"{hms(s.at_ms)} — {one_line(s.quote) if s.quote else 'no speech recorded nearby'}"))
    return out


def _conversation(conv: ConversationView) -> list[dict]:
    return [_block("heading_3", heading_text(conv, to=" to ", sep=", ", collapse_same_minute=True)),
            _block("paragraph", "\n".join(conversation_lines(conv)))]


def _insights(rec: InsightRecord) -> list[dict]:
    ins = rec.insight
    out = [_block("heading_3", "Insights")]
    if ins.summary:
        out.append(_block("paragraph", one_line(ins.summary)))
    for f in ins.follow_ups:
        text = one_line(f.text)
        out.append(_block("bulleted_list_item", f"{hms(f.at_ms)} — {text}" if f.at_ms is not None else text))
    if ins.people:
        out.append(_block("paragraph", f"People: {', '.join(ins.people)}"))
    if ins.topics:
        out.append(_block("paragraph", f"Topics: {', '.join(ins.topics)}"))
    out.append(_block("paragraph", f"Insights by {rec.model} ({display(rec.provider)}) at {hm(rec.generated_ms)}"))
    return out


def day_blocks(view: DayView, insight: Optional[InsightRecord]) -> list[dict]:
    """The children of the day's page (or of its owned block): Starred, the conversations, the Insights."""
    out: list[dict] = _starred(view) if view.stars else []
    for conv in view.conversations:
        out += _conversation(conv)
    if insight is not None and insight.state == "done" and insight.insight is not None:
        out += _insights(insight)
    return out


def _lines(block: dict) -> list[str]:
    body = block[block["type"]]
    lines = ["".join(r["text"]["content"] for r in body.get("rich_text", []))]
    for child in body.get("children", []):
        lines += _lines(child)
    return lines


def plain_text(blocks: list[dict]) -> str:
    """One line per block (a callout's own text, then its children's lines): what the connector reads back."""
    return "\n".join(line for b in blocks for line in _lines(b))


def content_hash(blocks: list[dict]) -> str:
    return hashlib.sha256(plain_text(blocks).encode("utf-8")).hexdigest()
