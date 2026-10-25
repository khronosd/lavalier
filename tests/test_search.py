from datetime import date

import pytest

from lavalier import db as db_module
from lavalier.db import Database
from lavalier.models import Segment, Transcript, Word
from lavalier.search import fts_query, search


def speech_transcript_with(text: str) -> Transcript:
    words = [Word(0.0, 0.4, f" {w}", 0.9) for w in text.split()]
    return Transcript(text, "en", "mlx-community/whisper-large-v3-turbo",
                      [Segment(0.0, 2.0, f" {text}", -0.293, 0.01, words)])


@pytest.fixture
def db_with_fixture_day(db, seeded_2026_10_23_subset):
    return db


@pytest.mark.parametrize("text,expected", [
    ("one two", '"one" "two"'),
    ('"one two" three', '"one two" "three"'),
    ("what did I decide?", '"what" "did" "I" "decide?"'),
    ("test AND", '"test" "AND"'),
    ('a lone "', '"a" "lone"'),
    ("", ""),
    ('say "hi', '"say" "hi"'),
    ('a"b', '"a""b"'),
    ('"" x', '"x"'),
    ("a\u0000b", '"ab"'),
])
def test_fts_query_shapes_user_text_safely(text, expected):
    assert fts_query(text) == expected


def test_search_finds_a_phrase_and_marks_it(db_with_fixture_day, cfg):
    hits = search(db_with_fixture_day, "one two three")
    assert hits and "<mark>one</mark>" in hits[0].snippet and hits[0].day == date(2026, 10, 23)
    assert hits[0].conversation_id is not None


def test_hit_time_matches_the_journal_line(db_with_fixture_day, cfg):
    from lavalier.journal import day_view
    view = day_view(db_with_fixture_day, date(2026, 10, 23), cfg, now_ms=0)
    lines = {(ln.clip_id, ln.seq): ln.at_ms for c in view.conversations for ln in c.lines}
    hits = search(db_with_fixture_day, "three")
    assert hits and all(lines[(h.clip_id, h.seq)] == h.at_ms for h in hits)


def test_empty_query_returns_nothing(db_with_fixture_day):
    assert search(db_with_fixture_day, "   ") == []


def test_search_never_raises_on_odd_input(db_with_fixture_day):
    for q in ['"', "AND", "NOT NEAR", "(", "*", "col:x", "a\u0000b", '""', "'", "^x", "x OR", '"a" "']:
        search(db_with_fixture_day, q)


def test_index_follows_set_transcript(db, clip_record):
    db.add_clip(clip_record)
    db.set_transcript(clip_record.clip_id, speech_transcript_with("rutabaga season"), "speech", 1)
    assert search(db, "rutabaga") and not search(db, "pineapple")
    db.set_transcript(clip_record.clip_id, speech_transcript_with("pineapple season"), "speech", 2)
    assert search(db, "pineapple") and not search(db, "rutabaga")


def test_a_hit_outside_any_conversation_has_no_conversation_id(db, clip_record):
    db.add_clip(clip_record)
    db.set_transcript(clip_record.clip_id, speech_transcript_with("rutabaga"), "speech", 1)
    hits = search(db, "rutabaga")
    assert len(hits) == 1 and hits[0].conversation_id is None


def test_migration_5_backfills_existing_segments(root, clip_record, monkeypatch):
    root.ensure()
    monkeypatch.setattr(db_module, "MIGRATIONS", db_module.MIGRATIONS[:4])
    with Database(root.db) as d:
        d.migrate()
        d.add_clip(clip_record)
        d.set_transcript(clip_record.clip_id, speech_transcript_with("one two"), "speech", 1)
        monkeypatch.undo()
        d.migrate()
        assert d.get_status("schema_version") == str(len(db_module.MIGRATIONS)) and search(d, "one two")


def test_a_noise_clip_is_never_a_hit_and_a_speech_clip_is(db, clip_record):
    import dataclasses
    noise = dataclasses.replace(clip_record, clip_id="clip_20261024T055514.111Z", first_ms=clip_record.first_ms - 60000,
                                last_ms=clip_record.first_ms - 55000)
    db.add_clip(clip_record)
    db.add_clip(noise)
    db.set_transcript(clip_record.clip_id, speech_transcript_with("rutabaga season"), "speech", 1)
    db.set_transcript(noise.clip_id, speech_transcript_with("rutabaga thank you"), "noise", 1)
    hits = search(db, "rutabaga")
    assert [h.clip_id for h in hits] == [clip_record.clip_id]
    db.set_classification(clip_record.clip_id, "noise")  # reclassified later: drops out too
    assert search(db, "rutabaga") == []
