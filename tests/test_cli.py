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
    monkeypatch.setenv("HOME", str(root.root.parent))  # empty HF cache
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
