from datetime import date

from conftest import T, speech_transcript, thank_you_transcript
from lavalier.pipeline import ProcessReport, process, retry_failed, status_summary
from lavalier.transcribe import FakeTranscriber


def test_process_runs_all_stages_and_isolates_failures(root, db, cfg, imported_and_decoded_three_clips):
    a, b, c = imported_and_decoded_three_clips
    tr = FakeTranscriber({a.clip_id: speech_transcript(), b.clip_id: RuntimeError("boom"),
                          c.clip_id: thank_you_transcript()})
    r = process(db, root, cfg, tr, now_ms=T(23, 30, 0))
    assert (r.transcribed, r.failed) == (2, 1) and r.days_written == [date(2026, 10, 23)]
    md = (root.days / "2026-10-23.md").read_text()
    assert "1 noise clip dropped" in md and db.clip(b.clip_id).classification == "failed"


def test_process_on_status_only_capture_writes_nothing(root, db, cfg, imported_status_only):
    assert db.days_dirty() == [date(2026, 10, 24)]  # the decoded status event dirtied its day
    r = process(db, root, cfg, FakeTranscriber({}), now_ms=0)
    assert r.days_written == [] and not list(root.days.glob("*.md"))
    assert db.days_dirty() == []


def test_a_failing_stage_does_not_stop_later_stages(root, db, cfg, imported_and_decoded_three_clips, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("stage down")

    monkeypatch.setattr("lavalier.pipeline.measure_loudness", boom)
    monkeypatch.setattr("lavalier.pipeline.sweep", boom)
    r = process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()), now_ms=T(23, 30, 0))
    assert r.loudness_measured == 0 and r.transcribed == 3 and r.days_written == [date(2026, 10, 23)]


def test_a_failing_day_does_not_stop_other_days(root, db, cfg, imported_and_decoded_three_clips, monkeypatch):
    db.mark_day_dirty(date(2026, 10, 22))
    real = __import__("lavalier.pipeline", fromlist=["write_day"]).write_day

    def flaky(db_, paths, day, cfg_, **k):
        if day == date(2026, 10, 22):
            raise RuntimeError("disk full")
        return real(db_, paths, day, cfg_, **k)

    monkeypatch.setattr("lavalier.pipeline.write_day", flaky)
    r = process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()), now_ms=T(23, 30, 0))
    assert r.days_written == [date(2026, 10, 23)]


def test_status_summary_reports_pending_and_next_deletion(root, db, cfg, imported_and_decoded_three_clips):
    s = status_summary(db, root, cfg, now_ms=T(23, 30, 0))
    assert s["pending_transcripts"] == 3 and s["next_deletion"] is None and s["audio_bytes"] > 0
    process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()), now_ms=T(23, 30, 0))
    s = status_summary(db, root, cfg, now_ms=T(23, 30, 0))
    assert s["pending_transcripts"] == 0 and s["next_deletion"] is not None
    assert isinstance(ProcessReport().days_written, list)


def test_day_written_before_process_gains_its_conversation(root, db, make_capture):
    """import -> write_day (as day --open or pin would) -> process: the file must not stay stale."""
    from pathlib import Path

    from lavalier.config import Config
    from lavalier.dayfile import write_day
    from lavalier.pipeline import import_and_decode

    cfg = Config(noise_mean_db=-60.0)  # the synthetic packet is quiet; let it count as speech
    packet = (Path(__file__).parent / "data" / "packet.bin").read_bytes()
    capture = make_capture([1, 2, 3], opus=packet, start_stop=True,
                           timestamps=[T(10, 0, 0), T(10, 0, 1), T(10, 0, 2)])
    import_and_decode(db, root, capture, capture_day=date(2026, 10, 23))
    day = date(2026, 10, 23)
    write_day(db, root, day, cfg, now_ms=T(10, 5, 0))
    assert "## Conversations" not in (root.days / "2026-10-23.md").read_text()
    r = process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()), now_ms=T(10, 5, 0))
    assert r.transcribed == 1 and r.days_written == [day]
    assert "## Conversations" in (root.days / "2026-10-23.md").read_text()


def test_missing_ffmpeg_skips_audio_stages_and_leaves_clips_pending(
        root, db, cfg, imported_and_decoded_three_clips, monkeypatch, caplog):
    monkeypatch.setattr("lavalier.pipeline.ffmpeg_available", lambda: False)
    with caplog.at_level("WARNING"):
        r = process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()), now_ms=T(23, 30, 0))
    assert (r.loudness_measured, r.transcribed, r.failed) == (0, 0, 0)
    assert len(db.clips_needing_transcript()) == 3 and db.count_failed_clips() == 0
    assert "ffmpeg not found" in caplog.text


def test_missing_model_skips_transcription_and_leaves_clips_pending(
        root, db, cfg, imported_and_decoded_three_clips, caplog):
    tr = FakeTranscriber({}, default=speech_transcript(), unavailable="model x is not cached")
    with caplog.at_level("WARNING"):
        r = process(db, root, cfg, tr, now_ms=T(23, 30, 0))
    assert (r.transcribed, r.failed) == (0, 0)
    assert len(db.clips_needing_transcript()) == 3 and db.count_failed_clips() == 0
    assert "model x is not cached" in caplog.text


def test_retry_failed_requeues_failed_clips(root, db, cfg, imported_and_decoded_three_clips):
    a, b, c = imported_and_decoded_three_clips
    tr = FakeTranscriber({b.clip_id: RuntimeError("boom")}, default=speech_transcript())
    process(db, root, cfg, tr, now_ms=T(23, 30, 0))
    assert db.count_failed_clips() == 1 and status_summary(db, root, cfg, now_ms=0)["failed_clips"] == 1
    assert retry_failed(db) == 1
    again = db.clip(b.clip_id)
    assert (again.classification, again.transcribed_at, again.mean_db) == (None, None, None)
    r = process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()), now_ms=T(23, 40, 0))
    assert (r.loudness_measured, r.transcribed, r.failed) == (1, 1, 0) and db.count_failed_clips() == 0


# --- R47: a drain re-sending pages a CLI import (instance 0) already holds ---

def test_drain_resending_pages_of_an_instance_zero_import_decodes_only_the_new_pages(root, db, make_capture):
    from datetime import date as _date
    from conftest import T
    from lavalier.pipeline import import_and_decode
    ts = [T(10, 0, s) for s in range(5)]
    earlier = make_capture([1, 2, 3], timestamps=ts[:3])
    imp0, clips0 = import_and_decode(db, root, earlier, capture_day=_date(2026, 10, 23))   # CLI: instance 0
    drain = make_capture([1, 2, 3, 4, 5], timestamps=ts)
    imp, clips = import_and_decode(db, root, drain, capture_day=_date(2026, 10, 24), storage_instance=0xA1B2C3D4E5F60718)
    assert (imp.pages_new, imp.pages_duplicate) == (2, 3)
    assert db.capture_decoded(imp.capture_id) and [c.first_page for c in clips] == [4]
    assert len(clips0) == 1 and db.clip(clips0[0].clip_id).capture_id == imp0.capture_id


# --- R50: recovering the field state, where the old exact page_seen let re-sent pages in ---

def _field_page(i, *, start=False):
    from builders import make_audio_flash_page, make_storage_buffer_msg
    fp = make_audio_flash_page(b"\xb8" + b"A" * 39, did_start_recording=start, absolute_timestamp_ms=T(10, 0, i))
    return make_storage_buffer_msg(page_index=i, flash_page=fp, ingest_type=2, session=1, run=1)


def _field_capture(path, pages):
    from pendant_client.decode import write_batch_ingest_request
    write_batch_ingest_request(messages=[_field_page(i, start=i == 1) for i in pages], ble_identifier="test", path=path)
    return path


def _insert_undecoded_drain(db, root, src, instance):
    """What the drain left behind before R47: its row, its installed copy, and every one of its
    pages registered under it with the real instance, the re-sent ones included."""
    import hashlib
    import shutil
    from pendant_client.decode import iter_messages_from_bin, storage_page_of
    from lavalier.pages import page_key
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    installed = root.captures / f"{sha[:12]}-{src.name}"
    shutil.copyfile(src, installed)
    messages = list(iter_messages_from_bin(installed))
    cid = db.add_capture(str(installed.relative_to(root.root)), sha, len(messages), False)
    for m in messages:
        sp = storage_page_of(m)
        db.add_page(page_key(sp, storage_instance=instance), cid, sp.session, sp.ingest_type, 0)
    return cid, installed


import pytest


@pytest.mark.parametrize("drain_pages", [[1, 2, 3, 4, 5], [2, 3, 4, 5]],
                         ids=["dups-from-first-page", "dups-from-mid-recording"])
def test_recovering_a_drain_that_holds_resent_pages_decodes_only_the_new_pages(root, db, tmp_path, drain_pages):
    from lavalier.pipeline import import_and_decode
    imp_a, clips_a = import_and_decode(db, root, _field_capture(tmp_path / "earlier.bin", [1, 2, 3]),
                                       capture_day=date(2026, 10, 23))                 # CLI import: instance 0
    assert [(c.first_page, c.last_page) for c in clips_a] == [(1, 3)]
    events_before = db._conn.execute("SELECT page_index, type, capture_id FROM events ORDER BY id").fetchall()
    cid_b, installed = _insert_undecoded_drain(db, root, _field_capture(tmp_path / "20261024T055640Z.bin", drain_pages),
                                               0xA1B2C3D4E5F60718)
    _, clips = import_and_decode(db, root, installed, capture_day=date(2026, 10, 24), storage_instance=0xA1B2C3D4E5F60718)
    assert [(c.first_page, c.last_page, c.capture_id) for c in clips] == [(4, 5, cid_b)]
    every = db._conn.execute("SELECT clip_id, first_page, last_page, capture_id FROM clips ORDER BY first_page").fetchall()
    assert [tuple(r) for r in every] == [(clips_a[0].clip_id, 1, 3, imp_a.capture_id), (clips[0].clip_id, 4, 5, cid_b)]
    events_after = db._conn.execute("SELECT page_index, type, capture_id FROM events ORDER BY id").fetchall()
    assert [tuple(r) for r in events_after[:len(events_before)]] == [tuple(r) for r in events_before]
    assert all(r["page_index"] > 3 for r in events_after[len(events_before):])     # nothing again for pages 1..3
    assert db.capture_decoded(cid_b) and installed.exists()


def test_sweep_marks_a_capture_decoded_when_every_page_is_already_held(root, db, seeded_fully_duplicated_undecoded_capture):
    from lavalier.capture import SINK_NAME
    from lavalier.pipeline import sweep_orphan_captures
    sweep_orphan_captures(db, root, min_age_s=0)
    assert db.capture_decoded(seeded_fully_duplicated_undecoded_capture) and not list(p for p in root.captures.iterdir() if SINK_NAME.match(p.name))
