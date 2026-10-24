from datetime import date

from conftest import T, speech_transcript, thank_you_transcript
from pendant_recorder.pipeline import ProcessReport, process, status_summary
from pendant_recorder.transcribe import FakeTranscriber


def test_process_runs_all_stages_and_isolates_failures(root, db, cfg, imported_and_decoded_three_clips):
    a, b, c = imported_and_decoded_three_clips
    tr = FakeTranscriber({a.clip_id: speech_transcript(), b.clip_id: RuntimeError("boom"),
                          c.clip_id: thank_you_transcript()})
    r = process(db, root, cfg, tr, now_ms=T(23, 30, 0))
    assert (r.transcribed, r.failed) == (2, 1) and r.days_written == [date(2026, 10, 23)]
    md = (root.days / "2026-10-23.md").read_text()
    assert "1 noise clip dropped" in md and db.clip(b.clip_id).classification == "failed"


def test_process_on_status_only_capture_writes_nothing(root, db, cfg, imported_status_only):
    r = process(db, root, cfg, FakeTranscriber({}), now_ms=0)
    assert r.days_written == [] and not list(root.days.glob("*.md"))


def test_a_failing_stage_does_not_stop_later_stages(root, db, cfg, imported_and_decoded_three_clips, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("stage down")

    monkeypatch.setattr("pendant_recorder.pipeline.measure_loudness", boom)
    monkeypatch.setattr("pendant_recorder.pipeline.sweep", boom)
    r = process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()), now_ms=T(23, 30, 0))
    assert r.loudness_measured == 0 and r.transcribed == 3 and r.days_written == [date(2026, 10, 23)]


def test_a_failing_day_does_not_stop_other_days(root, db, cfg, imported_and_decoded_three_clips, monkeypatch):
    db.mark_day_dirty(date(2026, 10, 22))
    real = __import__("pendant_recorder.pipeline", fromlist=["write_day"]).write_day

    def flaky(db_, paths, day, cfg_, **k):
        if day == date(2026, 10, 22):
            raise RuntimeError("disk full")
        return real(db_, paths, day, cfg_, **k)

    monkeypatch.setattr("pendant_recorder.pipeline.write_day", flaky)
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

    from pendant_recorder.config import Config
    from pendant_recorder.dayfile import write_day
    from pendant_recorder.pipeline import import_and_decode

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
