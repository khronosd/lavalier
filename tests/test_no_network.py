import os
import socket
from datetime import date

from conftest import speech_transcript
from pendant_recorder.pipeline import import_and_process
from pendant_recorder.transcribe import FakeTranscriber


def test_pipeline_runs_with_sockets_blocked(root, db, cfg, capture_file, monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    imp, rep = import_and_process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()),
                                  capture_file, now_ms=0, capture_day=date(2026, 10, 24))
    assert rep.days_written and os.environ.get("HF_HUB_OFFLINE") == "1"
