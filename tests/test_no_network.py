import os
import socket
from datetime import date

from conftest import speech_transcript
from pendant_recorder.pipeline import import_and_process
from pendant_recorder.transcribe import FakeTranscriber


def test_pipeline_runs_with_sockets_blocked(root, db, cfg, capture_file, monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("network access attempted")

    # patch the class too: catches early bindings and subclasses (ssl, http.client, urllib)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    imp, rep = import_and_process(db, root, cfg, FakeTranscriber({}, default=speech_transcript()),
                                  capture_file, now_ms=0, capture_day=date(2026, 10, 24))
    assert rep.days_written
    # the fake transcriber never loads the model; this only guards against removing the
    # os.environ.setdefault("HF_HUB_OFFLINE", "1") in transcribe.py
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
