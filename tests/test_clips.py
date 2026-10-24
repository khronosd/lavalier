from datetime import date

import pytest

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


def test_empty_import_marks_capture_decoded(root, db, make_capture):
    from pendant_recorder.pages import import_capture
    first = import_capture(db, root, make_capture([1, 2]))
    decode_new_pages(db, root, first, capture_day=date(2026, 10, 24))
    dup = import_capture(db, root, make_capture([2, 1]))  # another file, only pages already seen
    assert dup.capture_id != first.capture_id and dup.new_payloads == []
    assert decode_new_pages(db, root, dup, capture_day=date(2026, 10, 24)) == []
    assert dup.capture_id in [c[0] for c in db.captures_decoded_before(2**62)]


def test_empty_payloads_never_mark_a_capture_that_owns_pages(root, db, make_capture):
    from pendant_recorder.pages import ImportResult, import_capture
    imp = import_capture(db, root, make_capture([1, 2]))
    decode_new_pages(db, root, ImportResult(imp.capture_id, imp.messages, 0, 0, []), capture_day=date(2026, 10, 24))
    assert not db.capture_decoded(imp.capture_id)


def test_failed_decode_is_rerun_by_the_next_import(root, db, make_capture, monkeypatch):
    from pathlib import Path

    from pendant_recorder.db import Database
    from pendant_recorder.pipeline import import_and_decode
    from conftest import T

    packet = (Path(__file__).parent / "data" / "packet.bin").read_bytes()
    path = make_capture([1, 2, 3], opus=packet, start_stop=True,
                        timestamps=[T(10, 0, 0), T(10, 0, 1), T(10, 0, 2)])

    def boom(self, c):
        raise RuntimeError("crash in add_clip")

    monkeypatch.setattr(Database, "add_clip", boom)
    with pytest.raises(RuntimeError):
        import_and_decode(db, root, path, capture_day=date(2026, 10, 24))
    monkeypatch.undo()
    assert db.captures_decoded_before(2**62) == [] and db.clips_for_day(date(2026, 10, 23)) == []

    imp, clips = import_and_decode(db, root, path, capture_day=date(2026, 10, 24))
    assert imp.pages_new == 0 and len(clips) == 1
    assert db.clips_for_day(date(2026, 10, 23)) == clips and (root.root / clips[0].path).exists()
    assert [c[0] for c in db.captures_decoded_before(2**62)] == [imp.capture_id]


def test_failure_leaves_no_files_or_rows(root, db, imported_two_chunk_capture, monkeypatch):
    from pendant_recorder.db import Database

    def boom(self, e):
        raise RuntimeError("boom")

    monkeypatch.setattr(Database, "add_event", boom)
    try:
        decode_new_pages(db, root, imported_two_chunk_capture, capture_day=date(2026, 10, 24))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected failure")
    assert not list(root.audio.rglob("*.opus"))
    assert db.clips_for_day(date(2026, 10, 23)) == []


def test_zero_timestamp_recordings_get_distinct_ids(root, db, tmp_path):
    from pendant_client.decode import write_batch_ingest_request
    from builders import make_audio_flash_page, make_storage_buffer_msg
    from pendant_recorder.pages import import_capture

    def page(i, start=False, stop=False):
        fp = make_audio_flash_page(b"\xb8" + b"A" * 39, did_start_recording=start, did_stop_recording=stop)
        return make_storage_buffer_msg(page_index=i, flash_page=fp, ingest_type=2, session=1, run=1)

    path = tmp_path / "two-recordings.bin"
    write_batch_ingest_request(messages=[page(1, start=True), page(2, stop=True), page(3, start=True), page(4, stop=True)],
                               ble_identifier="test", path=path)
    clips = decode_new_pages(db, root, import_capture(db, root, path), capture_day=date(2026, 10, 24))
    assert len(clips) == 2 and clips[0].first_page != clips[1].first_page
    assert [c.clip_id for c in clips] == [f"clip_19700101T000000.000Z-p{c.first_page}" for c in clips]
    assert all((root.root / c.path).exists() for c in clips)


def test_valid_clock_ids_have_no_page_suffix(root, db, imported_two_chunk_capture):
    clips = decode_new_pages(db, root, imported_two_chunk_capture, capture_day=date(2026, 10, 24))
    assert [c.clip_id for c in clips] == ["clip_20261024T055609.085Z"]
