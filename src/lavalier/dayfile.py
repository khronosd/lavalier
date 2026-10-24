"""Render one day's conversations as a Markdown file."""

from datetime import date, datetime
from pathlib import Path

from lavalier.config import Config
from lavalier.db import Database
from lavalier.journal import ConversationView, DayView, StarView, day_view
from lavalier.models import ClipRecord
from lavalier.paths import Paths


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


def _frontmatter(view: DayView) -> str:
    n = len(view.conversations)
    speech = f"{_duration(view.speech_ms)} across {_plural(n, 'conversation', 'conversations')}"
    return (f"---\ndate: {view.day.isoformat()}\n"
            f"speech: {speech}; {_plural(view.noise_clips, 'noise clip', 'noise clips')} dropped\n"
            f"stars: {len(view.stars)}\n---\n")


def _starred(stars: list[StarView], convs: dict[str, ConversationView]) -> str:
    lines = ["## Starred"]
    for s in stars:  # already in time order
        if s.conversation_id is None:
            lines.append(f"- {_hms(s.at_ms)} ★ (no speech recorded nearby)")
            continue
        line = f"- {_hms(s.at_ms)} ★ in [{_hm(convs[s.conversation_id].start_ms)} conversation](#{s.conversation_id})"
        if s.quote:
            line += f' — "{s.quote}"'
        lines.append(line)
    return "\n".join(lines) + "\n"


def _conversation(conv: ConversationView) -> str:
    stars = "★" * len(conv.star_ms)
    head = f"### {_hm(conv.start_ms)}–{_hm(conv.end_ms)} · {_duration(conv.speech_ms)} speech"
    if stars:
        head += f" {stars}"
    if conv.pinned:
        head += " (pinned)"
    lines = [f"{head} {{#{conv.conversation_id}}}"]
    events = [(ln.at_ms, 1, f"[{_hms(ln.at_ms)}] {ln.text}") for ln in conv.lines]
    # A star pressed shortly before the conversation began has no place in the
    # transcript; it still counts in the heading and the Starred section.
    events += [(ms, 0, f"[{_hms(ms)}] ★") for ms in conv.star_ms if conv.start_ms <= ms <= conv.end_ms]
    lines += [text for _, _, text in sorted(events, key=lambda e: (e[0], e[1]))]
    return "\n".join(lines) + "\n"


def _audio_status(clips: list[ClipRecord], view: DayView) -> str:
    if view.audio_kept_for_good:
        return "Audio kept"
    if not any(c.path for c in clips):
        return "Audio deleted"
    if view.audio_until is None:
        return "Audio kept"
    return f"Audio kept until {view.audio_until.isoformat()}"


def _noise_section(clips: list[ClipRecord]) -> str:
    lines = ["## Noise clips"]
    for c in clips:
        if c.classification != "noise":
            continue
        db_text = "n/a" if c.mean_db is None else f"{c.mean_db:.1f} dB".replace("-", "−")
        lines.append(f"- {_hms(c.first_ms)} · {c.chunk_count * 20 / 1000:.1f} s · {db_text}")
    return "\n".join(lines) + "\n"


def render_day(db: Database, day: date, cfg: Config, *, now_ms: int, keep_noise: bool = False) -> str:
    view = day_view(db, day, cfg, now_ms=now_ms)
    clips = db.clips_for_day(day)
    convs = {c.conversation_id: c for c in view.conversations}

    models = []
    for conv in view.conversations:
        for cid in conv.clip_ids:
            t = db.transcript(cid)
            if t is not None:
                models.append(t.model)

    parts = [_frontmatter(view), f"# {day:%A} {day.isoformat()}\n"]
    if any(c.clock_suspect for c in clips):
        parts.append("> Clock was unset on the pendant; times in this file are approximate.\n")
    if view.stars:
        parts.append(_starred(view.stars, convs))
    if view.conversations:
        parts.append("## Conversations\n")
        parts += [_conversation(c) for c in view.conversations]

    model = models[0] if models else cfg.whisper_model
    # A day that never had clips (stars only) says nothing about audio.
    audio = f" {_audio_status(clips, view)}." if clips else ""
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
