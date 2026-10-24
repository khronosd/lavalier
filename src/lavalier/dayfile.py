"""Render one day's conversations as a Markdown file."""

from datetime import date, datetime
from pathlib import Path

from lavalier.config import Config
from lavalier.db import Database
from lavalier.group import orphan_stars, press_times
from lavalier.models import ClipRecord, Conversation, Transcript
from lavalier.paths import Paths
from lavalier.retention import deadline_ms

QUOTE_WINDOW_MS = 10_000


def _local(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000)


def _hms(ms: int) -> str:
    return f"{_local(ms):%H:%M:%S}"


def _hm(ms: int) -> str:
    return f"{_local(ms):%H:%M}"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _duration(ms: int) -> str:
    s = round(ms / 1000)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600}h {s % 3600 // 60}m"


class _Segment:
    def __init__(self, at_ms: int, text: str):
        self.at_ms = at_ms
        self.text = text.strip()


def _segments(db: Database, clips: list[ClipRecord]) -> tuple[list[_Segment], list[Transcript]]:
    segs, transcripts = [], []
    for c in clips:
        t = db.transcript(c.clip_id)
        if t is None:
            continue
        transcripts.append(t)
        segs += [_Segment(c.first_ms + round(s.start_s * 1000), s.text) for s in t.segments]
    segs.sort(key=lambda s: s.at_ms)
    return segs, transcripts


def _quote(star_ms: int, segs: list[_Segment]) -> str | None:
    for s in segs:
        if star_ms <= s.at_ms <= star_ms + QUOTE_WINDOW_MS:
            return s.text
    return None


def _frontmatter(day: date, convs: list[Conversation], n_noise: int, n_stars: int) -> str:
    speech_ms = sum(c.speech_ms for c in convs)
    speech = f"{_duration(speech_ms)} across {_plural(len(convs), 'conversation', 'conversations')}"
    return (f"---\ndate: {day.isoformat()}\n"
            f"speech: {speech}; {_plural(n_noise, 'noise clip', 'noise clips')} dropped\n"
            f"stars: {n_stars}\n---\n")


def _starred(entries: list[tuple[int, Conversation | None, str | None]]) -> str:
    lines = ["## Starred"]
    for ms, conv, quote in sorted(entries, key=lambda e: e[0]):
        if conv is None:
            lines.append(f"- {_hms(ms)} ★ (no speech recorded nearby)")
            continue
        line = f"- {_hms(ms)} ★ in [{_hm(conv.start_ms)} conversation](#{conv.conversation_id})"
        if quote:
            line += f' — "{quote}"'
        lines.append(line)
    return "\n".join(lines) + "\n"


def _conversation(conv: Conversation, segs: list[_Segment]) -> str:
    stars = "★" * len(conv.star_ms)
    head = f"### {_hm(conv.start_ms)}–{_hm(conv.end_ms)} · {_duration(conv.speech_ms)} speech"
    if stars:
        head += f" {stars}"
    if conv.pinned:
        head += " (pinned)"
    lines = [f"{head} {{#{conv.conversation_id}}}"]
    events = [(s.at_ms, 1, f"[{_hms(s.at_ms)}] {s.text} (speaker: )") for s in segs]
    # A star pressed shortly before the conversation began has no place in the
    # transcript; it still counts in the heading and the Starred section.
    events += [(ms, 0, f"[{_hms(ms)}] ★") for ms in conv.star_ms if conv.start_ms <= ms <= conv.end_ms]
    lines += [text for _, _, text in sorted(events, key=lambda e: (e[0], e[1]))]
    return "\n".join(lines) + "\n"


def _audio_status(clips: list[ClipRecord], protected_ids: set[str], cfg: Config) -> str:
    speech = [c for c in clips if c.classification == "speech"]
    if any(c.clip_id in protected_ids for c in speech):
        return "Audio kept"
    with_file = [c for c in clips if c.path]
    if not with_file:
        return "Audio deleted"
    deadlines = [d for c in with_file
                 if (d := deadline_ms(c, cfg, protected=False)) is not None]
    if not deadlines:
        return "Audio kept"
    return f"Audio kept until {_local(max(deadlines)).date().isoformat()}"


def _noise_section(clips: list[ClipRecord]) -> str:
    lines = ["## Noise clips"]
    for c in clips:
        if c.classification != "noise":
            continue
        db_text = "n/a" if c.mean_db is None else f"{c.mean_db:.1f} dB".replace("-", "−")
        lines.append(f"- {_hms(c.first_ms)} · {c.chunk_count * 20 / 1000:.1f} s · {db_text}")
    return "\n".join(lines) + "\n"


def render_day(db: Database, day: date, cfg: Config, *, now_ms: int, keep_noise: bool = False) -> str:
    clips = db.clips_for_day(day)
    by_id = {c.clip_id: c for c in clips}
    convs = db.conversations_for_day(day)
    n_noise = sum(1 for c in clips if c.classification == "noise")

    conv_segs, models = {}, []
    for conv in convs:
        segs, transcripts = _segments(db, [by_id[i] for i in conv.clip_ids if i in by_id])
        conv_segs[conv.conversation_id] = segs
        models += [t.model for t in transcripts]

    entries = [(ms, conv, _quote(ms, conv_segs[conv.conversation_id]))
               for conv in convs for ms in conv.star_ms]
    entries += [(ms, None, None) for ms in orphan_stars(press_times(db, day), convs)]

    parts = [_frontmatter(day, convs, n_noise, len(entries)),
             f"# {day:%A} {day.isoformat()}\n"]
    if any(c.clock_suspect for c in clips):
        parts.append("> Clock was unset on the pendant; times in this file are approximate.\n")
    if entries:
        parts.append(_starred(entries))
    if convs:
        parts.append("## Conversations\n")
        parts += [_conversation(c, conv_segs[c.conversation_id]) for c in convs]

    protected = {i for c in convs if c.star_ms or c.pinned for i in c.clip_ids}
    model = models[0] if models else cfg.whisper_model
    # A day that never had clips (stars only) says nothing about audio.
    audio = f" {_audio_status(clips, protected, cfg)}." if clips else ""
    parts.append(f"_Transcribed with {model}.{audio}_\n")
    if keep_noise:
        parts.append(_noise_section(clips))
    return "\n".join(parts)


def write_day(db: Database, paths: Paths, day: date, cfg: Config, *, now_ms: int) -> Path:
    text = render_day(db, day, cfg, now_ms=now_ms)
    paths.days.mkdir(parents=True, exist_ok=True)
    out = paths.days / f"{day.isoformat()}.md"
    out.write_text(text)
    db.mark_day_clean(day)
    return out
