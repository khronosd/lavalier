import os
import time

import pytest

from lavalier.models import DeviceSnapshot
from lavalier.paths import Paths


@pytest.fixture(autouse=True)
def _pacific_time():
    """The plan's expected local dates are for US Pacific; pin it."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


@pytest.fixture
def root(tmp_path):
    return Paths(tmp_path / "Pendant")


from datetime import date

from lavalier.db import Database
from lavalier.models import ClipRecord


@pytest.fixture
def clip_record():
    return ClipRecord(
        clip_id="clip_20261024T055609.085Z",
        path="audio/2026-10-23/clip_20261024T055609.085Z.opus",
        day=date(2026, 10, 23),
        first_ms=1792821369085,
        last_ms=1792821385067,
        chunk_count=800,
        first_page=7802,
        last_page=7813,
        run=1,
        capture_id=1,
        opened_with_start_marker=True,
        closed_with_stop_marker=True,
        clock_suspect=False,
    )


@pytest.fixture
def db(root):
    root.ensure()
    d = Database(root.db)
    d.migrate()
    try:
        yield d
    finally:
        d.close()


from pathlib import Path
from typing import Optional

from pendant_client.decode import write_batch_ingest_request

from builders import (
    make_audio_flash_page,
    make_button_page,
    make_storage_buffer_msg,
    make_storage_session_stop_page,
)
from lavalier.pages import import_capture


@pytest.fixture
def make_capture(tmp_path):
    counter = {"n": 0}

    def _make(pages: list[int], opus: bytes = b"\xb8" + b"A" * 39,
              timestamps: Optional[list[int]] = None, start_stop: bool = False,
              button_at: Optional[int] = None) -> Path:
        counter["n"] += 1
        path = tmp_path / f"capture{counter['n']}.bin"
        messages = []
        for n, i in enumerate(pages):
            flash_page = make_audio_flash_page(
                opus,
                did_start_recording=start_stop and n == 0,
                did_stop_recording=start_stop and n == len(pages) - 1,
                absolute_timestamp_ms=timestamps[n] if timestamps else 0,
            )
            messages.append(make_storage_buffer_msg(
                page_index=i, flash_page=flash_page, ingest_type=2, session=1, run=1))
        if button_at is not None:
            messages.append(make_storage_buffer_msg(
                page_index=max(pages) + 1,
                flash_page=make_button_page(button_at, absolute_timestamp_ms=button_at),
                ingest_type=2, session=1, run=1))
        write_batch_ingest_request(messages=messages, ble_identifier="test", path=path)
        return path

    return _make


@pytest.fixture
def capture_file(make_capture):
    return make_capture(pages=[1, 2, 3])


@pytest.fixture
def imported_two_chunk_capture(root, db, make_capture):
    path = make_capture([1, 2], timestamps=[1792821369085, 1792821371085],
                        start_stop=True, button_at=1792821372732)
    return import_capture(db, root, path)


@pytest.fixture
def imported_status_only_capture(root, db, tmp_path):
    path = tmp_path / "status.bin"
    msg = make_storage_buffer_msg(page_index=1, flash_page=make_storage_session_stop_page(),
                                  ingest_type=2, session=1, run=1)
    write_batch_ingest_request(messages=[msg], ble_identifier="test", path=path)
    return import_capture(db, root, path)


@pytest.fixture
def imported_capture_with_zero_timestamps(root, db, make_capture):
    return import_capture(db, root, make_capture([1, 2], timestamps=[0, 0]))


from pendant_client.decode import OggOpusWriter


def _write_opus(path: Path) -> Path:
    packet = (Path(__file__).parent / "data" / "packet.bin").read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    w = OggOpusWriter(path)
    for _ in range(50):
        w.add_packet(packet)
    w.close()
    return path


@pytest.fixture
def opus_clip(tmp_path):
    return _write_opus(tmp_path / "clip.opus")


@pytest.fixture
def two_clips_with_audio(root, db):
    specs = [("clip_20261024T055514.111Z", 1792821314111, 277),
             ("clip_20261024T055609.085Z", 1792821369085, 800)]
    clips = []
    for clip_id, first_ms, chunks in specs:
        rel = f"audio/2026-10-23/{clip_id}.opus"
        _write_opus(root.audio / "2026-10-23" / f"{clip_id}.opus")
        c = ClipRecord(
            clip_id=clip_id, path=rel, day=date(2026, 10, 23), first_ms=first_ms,
            last_ms=first_ms + 15000, chunk_count=chunks, first_page=1, last_page=2,
            run=1, capture_id=1, opened_with_start_marker=True,
            closed_with_stop_marker=True, clock_suspect=False,
        )
        db.add_clip(c)
        clips.append(c)
    return clips


import dataclasses

from lavalier.config import Config


@pytest.fixture
def cfg():
    return Config()


@pytest.fixture
def clip_at(clip_record):
    def _make(**overrides):
        return dataclasses.replace(clip_record, **overrides)

    return _make


from datetime import datetime, timezone


def T(h, m, s, ms=0) -> int:
    """Local 2026-10-23 timestamp in ms."""
    return int(datetime(2026, 10, 23, h, m, s, ms * 1000).timestamp() * 1000)


@pytest.fixture
def clip(clip_record):
    def _make(first_ms, last_ms, classification="speech"):
        stamp = datetime.fromtimestamp(first_ms / 1000, tz=timezone.utc)
        clip_id = f"clip_{stamp:%Y%m%dT%H%M%S}.{first_ms % 1000:03d}Z"
        return dataclasses.replace(
            clip_record, clip_id=clip_id, path=f"audio/x/{clip_id}.opus",
            day=datetime.fromtimestamp(first_ms / 1000).date(),
            first_ms=first_ms, last_ms=last_ms,
            chunk_count=(last_ms - first_ms) // 20, classification=classification)

    return _make


@pytest.fixture
def clip_rows_spanning_midnight(db, clip):
    c = clip(T(23, 58, 0), T(23, 58, 0) + 7 * 60 * 1000)
    c.day = date(2026, 10, 23)
    db.add_clip(c)
    return c


from lavalier.config import Config
from lavalier.group import rebuild_day
from lavalier.models import EventRecord, Segment, Transcript, Word


def _words(*specs):
    return [Word(s, e, w, p) for s, e, w, p in specs]


def _real_transcript() -> Transcript:
    ws1 = _words((0.0, 0.4, " test", 0.9), (0.4, 0.8, " test", 0.9), (0.8, 1.2, " test", 0.9),
                 (1.2, 1.6, " one", 0.9), (1.6, 2.0, " two", 0.9), (2.0, 2.32, " three", 0.9))
    ws2 = _words((3.96, 4.4, " test", 0.9), (4.4, 4.8, " test", 0.9), (4.8, 5.2, " test", 0.9),
                 (5.2, 5.6, " one", 0.9), (5.6, 6.0, " two", 0.9), (6.0, 6.34, " three", 0.9))
    text = "test test test one two three"
    return Transcript(
        text=f"{text} {text}", language="en", model="mlx-community/whisper-large-v3-turbo",
        segments=[Segment(0.0, 2.32, f" {text}", -0.293, 0.01, ws1),
                  Segment(3.96, 6.34, f" {text}", -0.293, 0.01, ws2)])


def _press(page, ms) -> EventRecord:
    return EventRecord(
        page_index=page, absolute_ms=ms, capture_id=1, type="button",
        payload={"type": "button", "button_event": "BUTTON_SHORT_PRESS",
                 "button_event_absolute_timestamp_ms": ms})


@pytest.fixture
def seeded_2026_10_23_subset(db, clip_record):
    cfg = Config()
    db.add_clip(dataclasses.replace(clip_record, classification=None, transcribed_at=None, mean_db=-27.2))
    db.set_transcript(clip_record.clip_id, _real_transcript(), "speech", T(23, 0, 0))
    for cid, first, db_ in (("clip_20261024T055514.111Z", 1792821314111, -44.2),
                            ("clip_20261024T060125.346Z", 1792821685346, -40.0)):
        db.add_clip(dataclasses.replace(
            clip_record, clip_id=cid, path=f"audio/2026-10-23/{cid}.opus", first_ms=first,
            last_ms=first + 5500, chunk_count=275, first_page=1, last_page=2, run=1,
            classification=None, transcribed_at=None, mean_db=db_))
        db.set_transcript(cid, Transcript("", "en", cfg.whisper_model, []), "noise", T(23, 0, 0))
    db.add_event(_press(7802, 1792821367981))
    db.add_event(_press(7805, 1792821372732))
    rebuild_day(db, date(2026, 10, 23), cfg)


@pytest.fixture
def seeded_bad_clock_day(db, clip_record):
    cfg = Config()
    first = int(datetime(2026, 10, 24, 9, 0, 0).timestamp() * 1000)
    c = dataclasses.replace(clip_record, clip_id="clip_20261024T160000.000Z", day=date(2026, 10, 24),
                            first_ms=first, last_ms=first + 16000, clock_suspect=True,
                            classification=None, transcribed_at=None)
    db.add_clip(c)
    db.set_transcript(c.clip_id, _real_transcript(), "speech", first + 60000)
    rebuild_day(db, date(2026, 10, 24), cfg)


@pytest.fixture
def seeded_orphan_star(db, clip_record):
    cfg = Config()
    db.add_clip(dataclasses.replace(clip_record, classification=None, transcribed_at=None))
    db.set_transcript(clip_record.clip_id, _real_transcript(), "speech", T(23, 0, 0))
    db.add_event(_press(7000, T(22, 50, 0)))
    rebuild_day(db, date(2026, 10, 23), cfg)


@pytest.fixture
def seeded_retention_day(root, db, cfg, clip_record):
    """Four speech-day clips 10 minutes apart: old, starred, fresh, failed."""
    day = date(2026, 10, 23)
    old_at = T(12, 0, 0)
    specs = [("old", T(10, 0, 0), "speech", old_at),
             ("starred", T(10, 10, 0), "speech", old_at),
             ("fresh", T(10, 20, 0), "speech", old_at + 2 * 86_400_000),
             ("failed", T(10, 30, 0), "failed", None)]
    ids = []
    for name, first, classification, transcribed_at in specs:
        clip_id = f"clip_{name}"
        rel = f"audio/{day.isoformat()}/{clip_id}.opus"
        _write_opus(root.audio / day.isoformat() / f"{clip_id}.opus")
        db.add_clip(dataclasses.replace(
            clip_record, clip_id=clip_id, path=rel, day=day, first_ms=first,
            last_ms=first + 15000, classification=None, transcribed_at=None))
        if classification == "failed":
            db.set_transcript(clip_id, Transcript("", "en", cfg.whisper_model, []), "failed", None)
        else:
            db.set_transcript(clip_id, _real_transcript(), classification, transcribed_at)
        ids.append(clip_id)
    db.add_event(_press(1, T(10, 10, 0)))
    rebuild_day(db, day, cfg)
    return tuple(db.clip(i) for i in ids)


@pytest.fixture
def imported_and_decoded_three_clips(root, db):
    """Three clips with real audio on 2026-10-23, 10 minutes apart; the day is dirty."""
    day = date(2026, 10, 23)
    clips = []
    for name, first in (("a", T(10, 0, 0)), ("b", T(10, 10, 0)), ("c", T(10, 20, 0))):
        clip_id = f"clip_{name}"
        rel = f"audio/{day.isoformat()}/{clip_id}.opus"
        _write_opus(root.audio / day.isoformat() / f"{clip_id}.opus")
        c = ClipRecord(
            clip_id=clip_id, path=rel, day=day, first_ms=first, last_ms=first + 15000,
            chunk_count=750, first_page=1, last_page=2, run=1, capture_id=1,
            opened_with_start_marker=True, closed_with_stop_marker=True, clock_suspect=False)
        db.add_clip(c)
        db.set_loudness(clip_id, -44.2 if name == "c" else -27.2, -10.0)  # the real rec0098 / rec0099 levels
        clips.append(c)
    db.mark_day_dirty(day)
    return tuple(clips)


@pytest.fixture
def imported_status_only(root, db, imported_status_only_capture):
    from lavalier.clips import decode_new_pages
    decode_new_pages(db, root, imported_status_only_capture, capture_day=date(2026, 10, 24))
    return imported_status_only_capture


def speech_transcript() -> Transcript:
    return _real_transcript()


def thank_you_transcript() -> Transcript:
    return Transcript("Thank you.", "en", "mlx-community/whisper-large-v3-turbo", [
        Segment(0, 1.88, " Thank you.", -0.953, 0.0, [Word(0, 0.28, "Thank", 0.05), Word(0.28, 1.88, "you.", 0.99)])])


@pytest.fixture
def snap():
    return DeviceSnapshot(1000, True, "LISTENING", 0, 786, 94, -10, "USB_DISCONNECTED", "1.1.3", 7)
