from datetime import date

from conftest import T
from pendant_recorder.group import group_clips, orphan_stars, rebuild_day


def test_gap_merges_and_splits(cfg, clip):
    a = clip(T(17,33,14), T(17,49,22)); b = clip(T(17,49,26), T(17,49,31)); c = clip(T(19,14,38), T(20,1,39))
    convs = group_clips([a, b, c], [], cfg)
    assert [(x.start_ms, x.end_ms) for x in convs] == [(a.first_ms, b.last_ms), (c.first_ms, c.last_ms)]
    assert convs[0].clip_ids == [a.clip_id, b.clip_id] and convs[0].conversation_id == "c-20261023-173314"


def test_star_before_clip_attaches_within_window(cfg, clip):
    c = clip(T(22,56,9,85), T(22,56,25,67))
    convs = group_clips([c], [T(22,56,7,981), T(22,56,12,732)], cfg)
    assert convs[0].star_ms == [T(22,56,7,981), T(22,56,12,732)]


def test_star_far_from_speech_is_orphan(cfg, clip):
    c = clip(T(22,56,9), T(22,56,25)); stars = [T(22,50,0)]
    convs = group_clips([c], stars, cfg)
    assert convs[0].star_ms == [] and orphan_stars(stars, convs) == stars


def test_midnight_conversation_belongs_to_start_day(root, db, cfg, clip_rows_spanning_midnight):
    convs = rebuild_day(db, date(2026,10,23), cfg)
    assert len(convs) == 1 and convs[0].day == date(2026,10,23)
    assert rebuild_day(db, date(2026,10,24), cfg) == []


def test_gap_boundaries(cfg, clip):
    a = clip(T(10,0,0), T(10,1,0))
    split = group_clips([a, clip(T(10,3,0), T(10,4,0))], [], cfg)
    merged = group_clips([a, clip(T(10,2,59,980), T(10,4,0))], [], cfg)
    assert len(split) == 2 and len(merged) == 1


def test_rebuild_day_stars_from_events(db, cfg, clip, caplog):
    from pendant_recorder.models import EventRecord
    c = clip(T(22,56,9), T(22,56,25))
    db.add_clip(c)

    def ev(page, at, type_, payload):
        db.add_event(EventRecord(page, at, type_, payload, 1))

    ev(1, T(22,56,12), "button", {"button_event": "BUTTON_SHORT_PRESS",
                                  "button_event_absolute_timestamp_ms": T(22,56,7)})
    ev(2, T(22,56,13), "button", {"button_event": "BUTTON_LONG_PRESS",
                                  "button_event_absolute_timestamp_ms": T(22,56,13)})
    ev(3, T(22,56,14), "other", {"button_event": "BUTTON_SHORT_PRESS",
                                 "button_event_absolute_timestamp_ms": T(22,56,14)})
    ev(4, T(22,56,20), "button", {"button_event": "BUTTON_SHORT_PRESS"})
    with caplog.at_level("WARNING"):
        convs = rebuild_day(db, date(2026,10,23), cfg)
    assert convs[0].star_ms == [T(22,56,7), T(22,56,20)]
    assert "no timestamp" in caplog.text
