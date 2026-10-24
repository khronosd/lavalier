"""Plain records shared by the state database and the pipeline stages."""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class PageKey:
    run: int
    index: int
    sha256: str


@dataclass
class ClipRecord:
    clip_id: str
    path: str  # relative to the state root
    day: date
    first_ms: int
    last_ms: int
    chunk_count: int
    first_page: int
    last_page: int
    run: int
    capture_id: int
    opened_with_start_marker: bool
    closed_with_stop_marker: bool
    clock_suspect: bool
    mean_db: Optional[float] = None
    peak_db: Optional[float] = None
    classification: Optional[str] = None  # "speech" | "noise" | "failed"
    transcribed_at: Optional[int] = None


@dataclass
class Word:
    start_s: float
    end_s: float
    word: str
    probability: float


@dataclass
class Segment:
    start_s: float
    end_s: float
    text: str
    avg_logprob: float
    no_speech_prob: float
    words: list[Word]


@dataclass
class Transcript:
    text: str
    language: str
    model: str
    segments: list[Segment]


@dataclass
class EventRecord:
    page_index: int
    absolute_ms: int
    type: str
    payload: dict
    capture_id: int


@dataclass
class Conversation:
    conversation_id: str
    day: date
    start_ms: int
    end_ms: int
    speech_ms: int
    clip_ids: list[str]
    star_ms: list[int]
    pinned: bool = False
    label: Optional[str] = None
