"""Merge a day's speech clips into conversations and attach starred moments."""

import logging
from datetime import date, datetime

from pendant_recorder.config import Config
from pendant_recorder.db import Database
from pendant_recorder.models import ClipRecord, Conversation

log = logging.getLogger(__name__)


def group_clips(clips: list[ClipRecord], stars_ms: list[int], cfg: Config) -> list[Conversation]:
    """Group speech clips (sorted by first_ms, one day) by time gap and attach stars."""
    gap_ms = cfg.conversation_gap_s * 1000
    groups: list[list[ClipRecord]] = []
    for clip in clips:
        if groups and clip.first_ms - groups[-1][-1].last_ms < gap_ms:
            groups[-1].append(clip)
        else:
            groups.append([clip])

    convs = []
    for g in groups:
        start = datetime.fromtimestamp(g[0].first_ms / 1000)
        convs.append(Conversation(
            conversation_id=f"c-{start:%Y%m%d-%H%M%S}",
            day=g[0].day,
            start_ms=g[0].first_ms,
            end_ms=g[-1].last_ms,
            speech_ms=sum(c.chunk_count * 20 for c in g),
            clip_ids=[c.clip_id for c in g],
            star_ms=[],
        ))

    window_ms = cfg.star_window_s * 1000
    for star in sorted(stars_ms):
        target = next((c for c in convs if c.start_ms <= star <= c.end_ms), None)
        if target is None:
            target = next((c for c in convs if star < c.start_ms <= star + window_ms), None)
        if target is not None:
            target.star_ms.append(star)
    return convs


def orphan_stars(stars_ms: list[int], convs: list[Conversation]) -> list[int]:
    """Stars that are attached to no conversation."""
    attached = {s for c in convs for s in c.star_ms}
    return [s for s in stars_ms if s not in attached]


def rebuild_day(db: Database, day: date, cfg: Config) -> list[Conversation]:
    """Regroup one day's speech clips and store the result."""
    clips = [c for c in db.clips_for_day(day) if c.classification == "speech"]
    stars = []
    for e in db.events_for_day(day, types=["button"]):
        if e.payload.get("button_event") != "BUTTON_SHORT_PRESS":
            continue
        ts = e.payload.get("button_event_absolute_timestamp_ms")
        if not ts:
            log.warning("short press on page %s has no timestamp; using event time", e.page_index)
            ts = e.absolute_ms
        stars.append(ts)
    convs = group_clips(clips, stars, cfg)
    db.replace_conversations(day, convs)
    return convs
