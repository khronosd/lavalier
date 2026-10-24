from datetime import date

from click.testing import CliRunner

from pendant_recorder.config import Config, save_config
from conftest import T, speech_transcript
from pendant_recorder.cli import main
from pendant_recorder.db import Database
from pendant_recorder.transcribe import FakeTranscriber


def db_for(root):
    return Database(root.db)


def test_cli_round_trip(root, make_capture, monkeypatch):
    packet = (__import__("pathlib").Path(__file__).parent / "data" / "packet.bin").read_bytes()
    capture = make_capture([1, 2, 3], opus=packet, start_stop=True,
                           timestamps=[T(10, 0, 0), T(10, 0, 1), T(10, 0, 2)])
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    # the synthetic packet is quiet (about -46 dB); lower the gate so the clip counts as speech
    save_config(Config(noise_mean_db=-60.0), root.config)
    monkeypatch.setattr("pendant_recorder.cli.MlxWhisperTranscriber",
                        lambda m, l: FakeTranscriber({}, default=speech_transcript()))
    r = CliRunner()
    assert r.invoke(main, ["import", str(capture), "--process"]).exit_code == 0
    assert "Transcribed 1" in r.invoke(main, ["status"]).output
    assert r.invoke(main, ["day", "2026-10-23"]).output.startswith("---\ndate: 2026-10-23")
    with db_for(root) as db:
        cid = db.conversations_for_day(date(2026, 10, 23))[0].conversation_id
    assert r.invoke(main, ["pin", cid]).exit_code == 0 and cid in r.invoke(main, ["status"]).output
    assert "unpinned" in r.invoke(main, ["unpin", cid]).output
    assert cid not in r.invoke(main, ["status"]).output
    assert r.invoke(main, ["retention", "--now"]).exit_code == 0


def test_pin_unknown_conversation_fails(root, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    res = CliRunner().invoke(main, ["pin", "nope"])
    assert res.exit_code != 0 and "no such conversation" in res.output


def test_doctor_reports_checks_and_exits_1_when_one_fails(root, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(root.root.parent / "hf-empty"))
    res = CliRunner().invoke(main, ["doctor"])
    assert "python >= 3.12" in res.output and "ffmpeg" in res.output
    assert "FAIL whisper model cached" in res.output and res.exit_code == 1


def test_import_without_process_still_decodes(root, make_capture, monkeypatch):
    packet = (__import__("pathlib").Path(__file__).parent / "data" / "packet.bin").read_bytes()
    capture = make_capture([1, 2, 3], opus=packet, start_stop=True,
                           timestamps=[T(10, 0, 0), T(10, 0, 1), T(10, 0, 2)])
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    assert CliRunner().invoke(main, ["import", str(capture)]).exit_code == 0
    with db_for(root) as db:
        assert db.clips_needing_loudness()
        assert db.get_status("last_import_iso")
    assert list(root.audio.rglob("*.opus"))


def test_download_model_runs_offline_free_subprocess(root, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    calls = []
    monkeypatch.setattr("pendant_recorder.cli.subprocess.run", lambda *a, **k: calls.append((a, k)))
    CliRunner().invoke(main, ["doctor", "--download-model"])
    (argv,), kw = calls[0]
    assert "HF_HUB_OFFLINE" not in kw["env"] and Config().whisper_model in argv


def test_day_open_with_keep_noise_is_a_usage_error(root, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    r = CliRunner().invoke(main, ["day", "2026-10-23", "--open", "--keep-noise"])
    assert r.exit_code == 2 and "--keep-noise only applies when printing" in r.output


def test_doctor_looks_for_the_model_in_the_hf_hub_cache(root, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    cache = root.root.parent / "hf"
    (cache / ("models--" + Config().whisper_model.replace("/", "--"))).mkdir(parents=True)
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(cache))
    assert "ok   whisper model cached" in CliRunner().invoke(main, ["doctor"]).output


def test_retry_failed_and_status_failed_count(root, monkeypatch, clip_record):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    root.ensure()
    with db_for(root) as db:
        db.migrate()
        db.add_clip(clip_record)
        db.set_classification(clip_record.clip_id, "failed")
    r = CliRunner()
    assert "Failed clips: 1 (retry-failed requeues them)" in r.invoke(main, ["status"]).output
    out = r.invoke(main, ["retry-failed"])
    assert out.exit_code == 0 and "Requeued 1 failed clips" in out.output
    assert "Failed clips: 0\n" in r.invoke(main, ["status"]).output


def test_newer_schema_is_a_clean_cli_error(root, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    root.ensure()
    with db_for(root) as db:
        db.migrate()
        db.set_status("schema_version", "999")
    res = CliRunner().invoke(main, ["status"])
    assert res.exit_code == 1 and "schema version 999 is newer" in res.output


def test_doctor_reports_an_unwritable_root_as_fail(tmp_path, monkeypatch):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    monkeypatch.setenv("PENDANT_ROOT", str(blocker / "Pendant"))
    res = CliRunner().invoke(main, ["doctor"])
    assert "FAIL state root writable" in res.output
    assert res.exit_code == 1 and isinstance(res.exception, SystemExit)
