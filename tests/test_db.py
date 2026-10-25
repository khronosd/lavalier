from dataclasses import replace
from datetime import date, datetime

import pytest

from lavalier import db as db_module
from lavalier.db import Database
from lavalier.models import (
    Conversation,
    DeviceSnapshot,
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
        assert d.get_status("schema_version") == str(len(db_module.MIGRATIONS))


def test_page_dedup_key(root):
    root.ensure()
    k = PageKey(run=2, index=7802, sha256="ab" * 32)
    with Database(root.db) as d:
        d.migrate()
        cid = d.add_capture("captures/a.bin", "ff" * 32, 10, True)
        assert not d.page_seen(k)
        _add_page_v3(d, k, cid, 199, 2, 1792821367981)
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
    ev = EventRecord(5, 1792821369085, "button", {"n": 1}, 1, day=d1)
    other = EventRecord(6, 1792821369086, "star", {}, 1, day=d1)
    far = EventRecord(7, 1792821369085 + 10 * 86400 * 1000, "button", {}, 1, day=date(2026, 11, 2))
    for e in (ev, other, far):
        db.add_event(e)
    assert db.events_for_day(d1) == [ev, other]
    assert db.events_for_day(d1, ["star"]) == [other]


def test_event_day_is_the_stored_day_not_the_timestamp(db):
    db.add_event(EventRecord(1, 0, "button", {}, 1, day=date(2026, 10, 24)))
    db.add_event(EventRecord(2, 1792821369085, "button", {}, 1))  # no day given: its local date
    assert [e.page_index for e in db.events_for_day(date(2026, 10, 24))] == [1]
    assert [e.page_index for e in db.events_for_day(date(2026, 10, 23))] == [2]


def test_migration_2_backfills_event_days(root, monkeypatch):
    root.ensure()
    monkeypatch.setattr(db_module, "MIGRATIONS", db_module.MIGRATIONS[:1])
    with Database(root.db) as d:
        d.migrate()
        cid = d._conn.execute(
            "INSERT INTO captures (path, sha256, message_count, complete, imported_at_ms) VALUES ('c', 's', 1, 1, ?)",
            (int(datetime(2026, 10, 24, 9, 0).timestamp() * 1000),)).lastrowid
        d._conn.execute("INSERT INTO events (page_index, absolute_ms, type, payload, capture_id) "
                        "VALUES (1, 1792821369085, 'button', '{}', ?), (2, 0, 'button', '{}', ?)", (cid, cid))
        d._conn.commit()
        monkeypatch.undo()
        d.migrate()
        assert [e.page_index for e in d.events_for_day(date(2026, 10, 23))] == [1]
        assert [e.page_index for e in d.events_for_day(date(2026, 10, 24))] == [2]


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


def test_clear_status_unsets_the_key(db):
    db.set_status("k", "1")
    db.clear_status("k")
    db.clear_status("never-set")
    assert db.get_status("k") is None


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


def test_clips_with_audio_for_capture(db, clip_record):
    db.add_clip(clip_record)
    db.add_clip(replace(clip_record, clip_id="other", capture_id=2))
    assert db.clips_with_audio_for_capture(1) == 1
    db.clear_clip_path(clip_record.clip_id)
    assert db.clips_with_audio_for_capture(1) == 0
    assert db.clips_with_audio_for_capture(2) == 1


def test_nested_transaction_commits_only_at_the_outermost(root, db, clip_record):
    db.add_clip(clip_record)
    other = Database(root.db)
    try:
        with db.transaction():
            with db.transaction():
                db.set_loudness(clip_record.clip_id, -20.0, -3.0)
            assert other.clip(clip_record.clip_id).mean_db is None  # inner exit did not commit
            db.set_classification(clip_record.clip_id, "speech")
        c = other.clip(clip_record.clip_id)
        assert (c.mean_db, c.classification) == (-20.0, "speech")
    finally:
        other.close()


def test_nested_transaction_rolls_back_everything_on_outer_error(db, clip_record):
    db.add_clip(clip_record)
    with pytest.raises(RuntimeError):
        with db.transaction():
            with db.transaction():
                db.set_loudness(clip_record.clip_id, -20.0, -3.0)
            raise RuntimeError("boom")
    assert db.clip(clip_record.clip_id).mean_db is None
    db.set_classification(clip_record.clip_id, "noise")  # depth is back to 0: writes commit again
    assert db.clip(clip_record.clip_id).classification == "noise"


def test_migrate_refuses_a_newer_schema(db):
    db.set_status("schema_version", str(len(db_module.MIGRATIONS) + 1))
    with pytest.raises(db_module.SchemaTooNewError, match="newer than this lavalier supports"):
        db.migrate()


def test_a_failing_migration_leaves_no_trace(root, monkeypatch):
    def bad(c):
        c.execute("CREATE TABLE half_done (x INTEGER)")
        raise RuntimeError("migration bug")

    root.ensure()
    monkeypatch.setattr(db_module, "MIGRATIONS", db_module.MIGRATIONS + [bad])
    with Database(root.db) as d:
        with pytest.raises(RuntimeError, match="migration bug"):
            d.migrate()
        assert d.get_status("schema_version") == str(len(db_module.MIGRATIONS) - 1)
        tables = {r[0] for r in d._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "half_done" not in tables and "clips" in tables


def test_unknown_confidence_round_trips_as_null(db, clip_record):
    t = Transcript("hi", "en", "m", [Segment(0.0, 1.0, "hi", None, None, [Word(0.0, 1.0, "hi", None)])])
    db.add_clip(clip_record)
    db.set_transcript(clip_record.clip_id, t, "noise", 1)
    assert db.transcript(clip_record.clip_id) == t


def test_migration_3_relaxes_confidence_not_null_and_keeps_rows(root, monkeypatch):
    root.ensure()
    monkeypatch.setattr(db_module, "MIGRATIONS", db_module.MIGRATIONS[:2])
    with Database(root.db) as d:
        d.migrate()
        d._conn.execute("INSERT INTO segments (clip_id, seq, start_s, end_s, text, avg_logprob, no_speech_prob) "
                        "VALUES ('c1', 0, 0.0, 1.0, 'hi', -0.3, 0.1)")
        d._conn.execute("INSERT INTO words (clip_id, segment_seq, seq, start_s, end_s, word, probability) "
                        "VALUES ('c1', 0, 0, 0.0, 1.0, 'hi', 0.9)")
        d._conn.commit()
        monkeypatch.undo()
        d.migrate()
        assert d.get_status("schema_version") == str(len(db_module.MIGRATIONS))
        assert tuple(d._conn.execute("SELECT avg_logprob, no_speech_prob FROM segments").fetchone()) == (-0.3, 0.1)
        assert tuple(d._conn.execute("SELECT probability FROM words").fetchone()) == (0.9,)
        d._conn.execute("INSERT INTO segments (clip_id, seq, start_s, end_s, text, avg_logprob, no_speech_prob) "
                        "VALUES ('c1', 1, 1.0, 2.0, 'x', NULL, NULL)")
        d._conn.execute("INSERT INTO words (clip_id, segment_seq, seq, start_s, end_s, word, probability) "
                        "VALUES ('c1', 1, 0, 1.0, 2.0, 'x', NULL)")


def test_device_status_round_trip_and_latest(db):
    snap = DeviceSnapshot(1000, True, "LISTENING", 0, 786, 94, 51, "USB_DISCONNECTED", "1.1.3", 11232415790841468546)
    db.record_device_status(snap, source="sync", charger_signal="current")
    db.record_device_status(replace(snap, read_at_ms=2000, recording_state="NOT_RECORDING"), source="live", charger_signal="none")
    latest, source, signal = db.latest_device_status()
    assert (latest.read_at_ms, latest.recording_state, source, signal) == (2000, "NOT_RECORDING", "live", "none")
    assert latest.storage_instance == 11232415790841468546
    assert snap.pages_waiting == 787
    assert replace(snap, oldest_page=5, newest_page=4).pages_waiting == 0


def test_sync_runs_and_last_drain(db):
    assert db.last_drain_ok_ms() is None
    r1 = db.start_sync_run(1000)
    db.finish_sync_run(r1, ended_ms=1500, outcome="skipped", reason="not on charger", pages=0, messages=0, capture_id=None, muted_by=None, unmute="n/a", error=None)
    r2 = db.start_sync_run(2000)
    db.finish_sync_run(r2, ended_ms=2900, outcome="drained", reason="pages>=1000", pages=1200, messages=1210, capture_id=None, muted_by="recorder", unmute="confirmed", error=None)
    assert db.last_drain_ok_ms() == 2900
    assert db.last_sync_run().outcome == "drained"


def test_migration_4_keeps_pages_and_defaults_storage_instance(root, monkeypatch):
    root.ensure()
    monkeypatch.setattr(db_module, "MIGRATIONS", db_module.MIGRATIONS[:3])
    with Database(root.db) as d:
        d.migrate()
        cid = d.add_capture("captures/a.bin", "ff" * 32, 1, True)
        _add_page_v3(d, PageKey(run=1, index=7, sha256="ab" * 32), cid, 100, 1, 1792821367981)
        monkeypatch.undo()
        d.migrate()
        assert d.get_status("schema_version") == str(len(db_module.MIGRATIONS))
        assert d.page_seen(PageKey(run=1, index=7, sha256="ab" * 32))                       # storage_instance defaults to 0
        assert d.page_seen(PageKey(run=1, index=7, sha256="ab" * 32, storage_instance=5))   # R47: 0 is unknown


def _add_page_v3(d, key, capture_id, session, ingest_type, absolute_ms):
    """Insert a page the way schema 3 stored it (no storage_instance column yet)."""
    d._conn.execute(
        'INSERT INTO pages (run, "index", sha256, capture_id, session, ingest_type, absolute_ms) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (key.run, key.index, key.sha256, capture_id, session, ingest_type, absolute_ms),
    )
    d._conn.commit()


def test_pages_differing_only_in_storage_instance_are_distinct(db):
    cid = db.add_capture("captures/a.bin", "ee" * 32, 1, True)
    k0 = PageKey(run=1, index=7, sha256="ab" * 32, storage_instance=0)
    k1 = PageKey(run=1, index=7, sha256="ab" * 32, storage_instance=5)
    db.add_page(k0, cid, 100, 1, 1792821367981)
    db.add_page(k1, cid, 100, 1, 1792821367981)
    assert db.page_seen(k0) and db.page_seen(k1)


@pytest.mark.parametrize("instance", [2**63 - 1, 2**63, 2**64 - 1])
def test_u64_storage_instance_round_trips_on_both_tables(db, instance):
    snap = DeviceSnapshot(1000, True, "LISTENING", 0, 1, 90, 0, "USB_DISCONNECTED", "1.1.3", instance)
    db.record_device_status(snap, source="sync", charger_signal="none")
    assert db.latest_device_status()[0].storage_instance == instance
    cid = db.add_capture("captures/u.bin", "dd" * 32, 1, True)
    key = PageKey(run=1, index=3, sha256="cd" * 32, storage_instance=instance)
    db.add_page(key, cid, 100, 1, 1792821367981)
    assert db.page_seen(key)
    assert db.page_seen(PageKey(run=1, index=3, sha256="cd" * 32, storage_instance=0))   # R47: 0 is unknown
    keys = db.pages_for_capture(cid)
    assert keys == [key] and keys[0].storage_instance == instance


def test_connections_wait_for_a_busy_database(root):
    from lavalier.db import Database
    root.ensure()
    d = Database(root.db)
    try:
        assert d._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
    finally:
        d.close()


# --- R47: storage_instance 0 means "unknown", never a different storage ---

def test_page_seen_treats_instance_zero_as_unknown_on_either_side(db):
    cid = db.add_capture("captures/z.bin", "ee" * 32, 2, True)
    db.add_page(PageKey(run=1, index=7, sha256="ab" * 32, storage_instance=0), cid, 100, 1, 1792821367981)
    db.add_page(PageKey(run=1, index=8, sha256="ab" * 32, storage_instance=2**64 - 1), cid, 100, 1, 1792821367981)
    assert db.page_seen(PageKey(run=1, index=7, sha256="ab" * 32, storage_instance=2**64 - 1))
    assert db.page_seen(PageKey(run=1, index=8, sha256="ab" * 32, storage_instance=0))


def test_page_seen_keeps_two_known_instances_apart(db):
    cid = db.add_capture("captures/z.bin", "ee" * 32, 1, True)
    db.add_page(PageKey(run=1, index=7, sha256="ab" * 32, storage_instance=5), cid, 100, 1, 1792821367981)
    assert db.page_seen(PageKey(run=1, index=7, sha256="ab" * 32, storage_instance=5))
    assert not db.page_seen(PageKey(run=1, index=7, sha256="ab" * 32, storage_instance=6))


def test_conversation_lookup_by_id(db, seeded_2026_10_23_subset):
    from conftest import CONV
    c = db.conversation(CONV)
    assert c is not None and c.conversation_id == CONV and c.day.isoformat() == "2026-10-23" and not c.pinned
    db.pin(CONV)
    assert db.conversation(CONV).pinned and db.conversation("c-nope") is None


def test_days_summary_counts_one_row_per_day_newest_first(db, seeded_2026_10_23_subset):
    rows = db.days_summary()
    assert [tuple(r) for r in rows] == [("2026-10-23", 16000, 1, 2, 2)]


def test_migration_6_adds_insights_and_round_trips(db):
    from lavalier.insights.schema import FollowUp, Insight
    d = date(2026, 10, 23)
    ins = Insight("s", [FollowUp("Call", 5, None)], ["Remy"], ["t"])
    db.set_insight(d, provider="ollama", model="m", prompt_version=1, generated_ms=5, input_chars=10, insight=ins)
    r = db.insight(d)
    assert r.state == "done" and r.insight == ins and r.error is None and r.input_chars == 10
    assert db.insight(date(2026, 10, 22)) is None and [x.day for x in db.insights_all()] == [d]
    assert len(db_module.MIGRATIONS) >= 6


def test_migration_7_adds_truncated_and_keeps_rows(root, monkeypatch):
    from lavalier.insights.schema import Insight
    root.ensure()
    monkeypatch.setattr(db_module, "MIGRATIONS", db_module.MIGRATIONS[:6])
    d = date(2026, 10, 23)
    with Database(root.db) as dbx:
        dbx.migrate()
        dbx._conn.execute(
            "INSERT INTO insights (day, state, provider, model, prompt_version, generated_ms, input_chars, summary, "
            "follow_ups, people, topics, error) VALUES (?, 'done', 'p', 'm', 1, 5, 10, 's', '[]', '[]', '[]', NULL)",
            (d.isoformat(),))
        dbx._conn.commit()
        monkeypatch.undo()
        dbx.migrate()
        assert dbx.get_status("schema_version") == str(len(db_module.MIGRATIONS)) and len(db_module.MIGRATIONS) >= 7
        r = dbx.insight(d)
        assert r.state == "done" and r.insight == Insight("s", [], [], []) and r.truncated is False
        kw = dict(provider="p", model="m", prompt_version=1, generated_ms=1, input_chars=2)
        dbx.set_insight(d, insight=Insight("s2", [], [], []), truncated=True, **kw)
        assert dbx.insight(d).truncated is True
        dbx.set_insight_error(d, error="e", truncated=True, **kw)
        assert dbx.insight(d).truncated is True
        dbx.set_insight_error(d, error="e", **kw)
        assert dbx.insight(d).truncated is False


def test_set_insight_error_replaces_a_done_row(db):
    from lavalier.insights.schema import Insight
    d = date(2026, 10, 23)
    kw = dict(provider="p", model="m", prompt_version=1, generated_ms=1, input_chars=2)
    db.set_insight(d, insight=Insight("s", [], [], []), **kw)
    db.set_insight_error(d, error="boom", **kw)
    r = db.insight(d)
    assert r.state == "error" and r.error == "boom" and r.insight is None and db.insights_all() == []
    db.set_insight(d, insight=Insight("s2", [], [], []), **kw)
    assert db.insight(d).insight.summary == "s2"


def test_insights_all_is_newest_day_first(db):
    from lavalier.insights.schema import Insight
    for d in (date(2026, 10, 21), date(2026, 10, 23), date(2026, 10, 22)):
        db.set_insight(d, provider="p", model="m", prompt_version=1, generated_ms=1, input_chars=2, insight=Insight("s", [], [], []))
    assert [r.day.day for r in db.insights_all()] == [23, 22, 21]


def test_days_with_speech_skips_noise_only_days(db, clip):
    from conftest import T
    from datetime import timedelta
    day = lambda n: clip(T(10, 0, 0) + n * 86_400_000, T(10, 1, 0) + n * 86_400_000)
    assert db.days_with_speech() == []
    later, noise, earlier = day(1), day(0), day(-1)
    later.classification = "speech"; earlier.classification = "speech"; noise.classification = "noise"
    for c in (later, noise, earlier):
        db.add_clip(c)
    db.add_clip(clip(T(11, 0, 0) - 86_400_000, T(11, 1, 0) - 86_400_000))  # second speech clip, same day
    assert db.days_with_speech() == [earlier.day, later.day]
