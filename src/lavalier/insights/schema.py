"""The reply every provider is asked for, and the hand-written validator for it."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

PROMPT_VERSION = 1

INSIGHT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "follow_ups", "people", "topics"],
    "properties": {
        "summary": {"type": "string"},
        "follow_ups": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "time"],
                "properties": {"text": {"type": "string"}, "time": {"type": "string", "pattern": "^[0-9]{2}:[0-9]{2}:[0-9]{2}$"}},
            },
        },
        "people": {"type": "array", "items": {"type": "string"}},
        "topics": {"type": "array", "items": {"type": "string"}},
    },
}

_TIME = re.compile(r"([0-9]{2}):([0-9]{2}):([0-9]{2})")


@dataclass(frozen=True)
class FollowUp:
    text: str
    at_ms: Optional[int]
    line_id: Optional[str]


@dataclass(frozen=True)
class Insight:
    summary: str
    follow_ups: list[FollowUp]
    people: list[str]
    topics: list[str]


class InsightError(ValueError):
    """The model's reply does not match INSIGHT_SCHEMA; the message names the first bad field."""


def _str(v: object, name: str) -> str:
    if not isinstance(v, str):
        raise InsightError(f"{name} must be a string, got {type(v).__name__}")
    return v.strip()


def _strings(data: dict, name: str) -> list[str]:
    items = data[name]
    if not isinstance(items, list):
        raise InsightError(f"{name} must be an array, got {type(items).__name__}")
    out = [_str(v, f"{name}[{i}]") for i, v in enumerate(items)]
    return list(dict.fromkeys(s for s in out if s))


def _follow_up(item: object, i: int, day: date) -> Optional[FollowUp]:
    where = f"follow_ups[{i}]"
    if not isinstance(item, dict):
        raise InsightError(f"{where} must be an object, got {type(item).__name__}")
    for k in ("text", "time"):
        if k not in item:
            raise InsightError(f"{where}.{k} is missing")
    text = _str(item["text"], f"{where}.text")
    t = _str(item["time"], f"{where}.time")
    m = _TIME.fullmatch(t)
    if not m or int(m[1]) > 23 or int(m[2]) > 59 or int(m[3]) > 59:
        raise InsightError(f"{where}.time must look like HH:MM:SS, got {t!r}")
    if not text:
        return None
    # a time in a repeated (fall-back) hour maps to its first occurrence (fold=0)
    local = datetime.combine(day, time(int(m[1]), int(m[2]), int(m[3]))).astimezone()
    return FollowUp(text, int(local.timestamp() * 1000), None)


def parse_reply(data: object, day: date) -> Insight:
    if not isinstance(data, dict):
        raise InsightError(f"reply must be an object, got {type(data).__name__}")
    for k in INSIGHT_SCHEMA["required"]:
        if k not in data:
            raise InsightError(f"{k} is missing")
    summary = _str(data["summary"], "summary")
    raw = data["follow_ups"]
    if not isinstance(raw, list):
        raise InsightError(f"follow_ups must be an array, got {type(raw).__name__}")
    ups = [f for i, item in enumerate(raw) if (f := _follow_up(item, i, day))]
    return Insight(summary, ups, _strings(data, "people"), _strings(data, "topics"))
