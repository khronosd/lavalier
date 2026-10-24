from datetime import date

from pendant_recorder.clips import clip_id_for, day_for, decode_new_pages


def test_clip_id_is_utc_millis():
    assert clip_id_for(1792821369085) == "clip_20261024T055609.085Z"


def test_day_for_uses_local_date_and_flags_bad_clock():
    assert day_for(1792821369085, fallback=date(2026, 1, 1)) == (date(2026, 10, 23), False)   # 22:56 PDT
    assert day_for(1000, fallback=date(2026, 10, 24)) == (date(2026, 10, 24), True)


def test_decode_new_pages_writes_clip_and_events(root, db, imported_two_chunk_capture):
    clips = decode_new_pages(db, root, imported_two_chunk_capture, capture_day=date(2026, 10, 24))
    assert len(clips) == 1 and (root.root / clips[0].path).exists() and clips[0].chunk_count == 2
    assert [e.type for e in db.events_for_day(clips[0].day)] == ["recording_start", "recording_stop", "button"]
    assert db.days_dirty() == [clips[0].day]


def test_status_only_capture_yields_no_files(root, db, imported_status_only_capture):
    assert decode_new_pages(db, root, imported_status_only_capture, capture_day=date(2026, 10, 24)) == []
    assert not list(root.audio.rglob("*.opus"))


def test_bad_clock_pages_file_under_capture_day(root, db, imported_capture_with_zero_timestamps):
    clips = decode_new_pages(db, root, imported_capture_with_zero_timestamps, capture_day=date(2026, 10, 24))
    assert clips[0].day == date(2026, 10, 24) and clips[0].clock_suspect is True
