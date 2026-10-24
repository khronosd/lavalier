from dataclasses import replace
from datetime import date, datetime

from pendant_recorder import db as db_module
from pendant_recorder.db import Database
from pendant_recorder.models import (
    Conversation,
    EventRecord,
    PageKey,
    Segment,
    Transcript,
    Word,
)


def test_migrate_is_idempotent(root):
    root.ensure()
    with Database(root.db) as d:
        d.migrate()
        d.migrate()
        assert d.get_status("schema_version") == "1"


def test_page_dedup_key(root):
    root.ensure()
    k = PageKey(run=2, index=7802, sha256="ab" * 32)
    with Database(root.db) as d:
        d.migrate()
        cid = d.add_capture("captures/a.bin", "ff" * 32, 10, True)
        assert not d.page_seen(k)
        d.add_page(k, cid, 199, 2, 1792821367981)
        assert d.page_seen(k)
        assert not d.page_seen(PageKey(run=2, index=7802, sha256="cd" * 32))


def test_clip_transcript_round_trip(root, clip_record):
    root.ensure()
    t = Transcript(
        text="test one two three",
        language="en",
        model="m",
        segments=[
            Segment(0.0, 2.32, "test one two three", -0.29, 0.0, [Word(0.0, 0.32, "test", 0.49)])
        ],
    )
    with Database(root.db) as d:
        d.migrate()
        d.add_clip(clip_record)
        d.set_transcript(clip_record.clip_id, t, "speech", 1)
        assert d.transcript(clip_record.clip_id) == t
        assert d.clip(clip_record.clip_id).classification == "speech"
        assert d.clips_needing_transcript() == []


def test_replace_conversations_keeps_pins(root):
    root.ensure()
    c = Conversation("c-225609", date(2026, 10, 23), 1, 2, 1, ["clip_a"], [])
    with Database(root.db) as d:
        d.migrate()
        d.replace_conversations(c.day, [c])
        d.pin("c-225609")
        d.replace_conversations(c.day, [c])
        assert d.conversations_for_day(c.day)[0].pinned is True
        d.unpin("c-225609")
        assert d.conversations_for_day(c.day)[0].pinned is False


def test_captures(db, monkeypatch):
    monkeypatch.setattr(db_module, "now_ms", lambda: 1000)
    cid = db.add_capture("captures/a.bin", "aa" * 32, 5, False)
    assert db.capture_by_sha("aa" * 32) == cid
    assert db.capture_by_sha("bb" * 32) is None
    assert db.captures_decoded_before(2000) == []
    db.mark_capture_decoded(cid)
    assert db.captures_decoded_before(999) == []
    assert db.captures_decoded_before(1000) == [(cid, "captures/a.bin")]


def test_loudness_and_classification_queues(db, clip_record):
    db.add_clip(clip_record)
    assert db.clip(clip_record.clip_id) == clip_record
    assert [c.clip_id for c in db.clips_needing_loudness()] == [clip_record.clip_id]
    assert [c.clip_id for c in db.clips_needing_transcript()] == [clip_record.clip_id]
    db.set_loudness(clip_record.clip_id, -30.5, -3.0)
    c = db.clip(clip_record.clip_id)
    assert (c.mean_db, c.peak_db) == (-30.5, -3.0)
    assert db.clips_needing_loudness() == []
    db.set_classification(clip_record.clip_id, "failed")
    assert db.clips_needing_transcript() == []
    assert db.clips_for_day(clip_record.day) == [db.clip(clip_record.clip_id)]
    assert db.clips_for_day(date(2026, 1, 1)) == []
    assert db.days_with_clips() == [clip_record.day]


def test_retention_queries(db, clip_record):
    db.add_clip(clip_record)
    assert db.clips_with_audio_older_than(10**15) == []
    db.set_transcript(clip_record.clip_id, Transcript("x", "en", "m", []), "noise", 500)
    assert db.clips_with_audio_older_than(499) == []
    assert [c.clip_id for c in db.clips_with_audio_older_than(500)] == [clip_record.clip_id]
    db.clear_clip_path(clip_record.clip_id)
    assert db.clip(clip_record.clip_id).path == ""
    assert db.clips_with_audio_older_than(10**15) == []


def test_events(db):
    d1 = datetime.fromtimestamp(1792821369085 / 1000).date()
    ev = EventRecord(5, 1792821369085, "button", {"n": 1}, 1)
    other = EventRecord(6, 1792821369086, "star", {}, 1)
    far = EventRecord(7, 1792821369085 + 10 * 86400 * 1000, "button", {}, 1)
    for e in (ev, other, far):
        db.add_event(e)
    assert db.events_for_day(d1) == [ev, other]
    assert db.events_for_day(d1, ["star"]) == [other]


def test_conversation_round_trip_and_day_state(db):
    d1 = date(2026, 10, 23)
    c = Conversation("c-1", d1, 1, 9, 5, ["clip_a", "clip_b"], [3, 4], label="hi")
    db.replace_conversations(d1, [c])
    assert db.conversations_for_day(d1) == [c]
    db.replace_conversations(d1, [replace(c, conversation_id="c-2", clip_ids=["clip_a"])])
    assert [x.conversation_id for x in db.conversations_for_day(d1)] == ["c-2"]
    assert db.days_dirty() == []
    db.mark_day_dirty(d1)
    assert db.days_dirty() == [d1]
    db.mark_day_clean(d1)
    assert db.days_dirty() == []


def test_status(db):
    assert db.get_status("k") is None
    db.set_status("k", "1")
    db.set_status("k", "2")
    assert db.get_status("k") == "2"


def test_set_loudness_rolls_back_with_transaction(db, clip_record):
    db.add_clip(clip_record)
    try:
        with db.transaction():
            db.set_loudness(clip_record.clip_id, -20.0, -3.0)
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert db.clip(clip_record.clip_id).mean_db is None


def test_set_loudness_persists_outside_transaction(db, clip_record):
    db.add_clip(clip_record)
    db.set_loudness(clip_record.clip_id, -20.0, -3.0)
    c = db.clip(clip_record.clip_id)
    assert (c.mean_db, c.peak_db) == (-20.0, -3.0)
