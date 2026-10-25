import os
import struct
import time
from unittest import mock

import pytest

from lavalier.models import DeviceSnapshot
from lavalier.paths import Paths


@pytest.fixture(autouse=True)
def _pacific_time():
    """The plan's expected local dates are for US Pacific; pin it."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


@pytest.fixture(autouse=True)
def _isolated_state_root(tmp_path, monkeypatch):
    """No test may touch the real ~/Pendant: the default state root is a per-test tmp directory."""
    monkeypatch.setenv("PENDANT_ROOT", str(tmp_path / "default-root"))


@pytest.fixture
def root(tmp_path):
    return Paths(tmp_path / "Pendant")


from datetime import date

from lavalier.db import Database
from lavalier.models import ClipRecord


@pytest.fixture
def clip_record():
    return ClipRecord(
        clip_id="clip_20261024T055609.085Z",
        path="audio/2026-10-23/clip_20261024T055609.085Z.opus",
        day=date(2026, 10, 23),
        first_ms=1792821369085,
        last_ms=1792821385067,
        chunk_count=800,
        first_page=7802,
        last_page=7813,
        run=1,
        capture_id=1,
        opened_with_start_marker=True,
        closed_with_stop_marker=True,
        clock_suspect=False,
    )


@pytest.fixture
def db(root):
    root.ensure()
    d = Database(root.db)
    d.migrate()
    try:
        yield d
    finally:
        d.close()


from pathlib import Path
from typing import Optional

from pendant_client.decode import write_batch_ingest_request

from builders import (
    make_audio_flash_page,
    make_button_page,
    make_storage_buffer_msg,
    make_storage_session_stop_page,
)
from lavalier.pages import import_capture


@pytest.fixture
def make_capture(tmp_path):
    counter = {"n": 0}

    def _make(pages: list[int], opus: bytes = b"\xb8" + b"A" * 39,
              timestamps: Optional[list[int]] = None, start_stop: bool = False,
              button_at: Optional[int] = None) -> Path:
        counter["n"] += 1
        path = tmp_path / f"capture{counter['n']}.bin"
        messages = []
        for n, i in enumerate(pages):
            flash_page = make_audio_flash_page(
                opus,
                did_start_recording=start_stop and n == 0,
                did_stop_recording=start_stop and n == len(pages) - 1,
                absolute_timestamp_ms=timestamps[n] if timestamps else 0,
            )
            messages.append(make_storage_buffer_msg(
                page_index=i, flash_page=flash_page, ingest_type=2, session=1, run=1))
        if button_at is not None:
            messages.append(make_storage_buffer_msg(
                page_index=max(pages) + 1,
                flash_page=make_button_page(button_at, absolute_timestamp_ms=button_at),
                ingest_type=2, session=1, run=1))
        write_batch_ingest_request(messages=messages, ble_identifier="test", path=path)
        return path

    return _make


@pytest.fixture
def capture_file(make_capture):
    return make_capture(pages=[1, 2, 3])


@pytest.fixture
def imported_two_chunk_capture(root, db, make_capture):
    path = make_capture([1, 2], timestamps=[1792821369085, 1792821371085],
                        start_stop=True, button_at=1792821372732)
    return import_capture(db, root, path)


@pytest.fixture
def imported_status_only_capture(root, db, tmp_path):
    path = tmp_path / "status.bin"
    msg = make_storage_buffer_msg(page_index=1, flash_page=make_storage_session_stop_page(),
                                  ingest_type=2, session=1, run=1)
    write_batch_ingest_request(messages=[msg], ble_identifier="test", path=path)
    return import_capture(db, root, path)


@pytest.fixture
def imported_capture_with_zero_timestamps(root, db, make_capture):
    return import_capture(db, root, make_capture([1, 2], timestamps=[0, 0]))


from pendant_client.decode import OggOpusWriter


def _write_opus(path: Path) -> Path:
    packet = (Path(__file__).parent / "data" / "packet.bin").read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    # fixed stream serial (low byte not 0x47) so the suite never depends on a random draw
    with mock.patch("os.urandom", return_value=struct.pack("<I", 0x0000a5e7)):
        w = OggOpusWriter(path)
    for _ in range(50):
        w.add_packet(packet)
    w.close()
    return path


@pytest.fixture
def opus_clip(tmp_path):
    return _write_opus(tmp_path / "clip.opus")


@pytest.fixture
def two_clips_with_audio(root, db):
    specs = [("clip_20261024T055514.111Z", 1792821314111, 277),
             ("clip_20261024T055609.085Z", 1792821369085, 800)]
    clips = []
    for clip_id, first_ms, chunks in specs:
        rel = f"audio/2026-10-23/{clip_id}.opus"
        _write_opus(root.audio / "2026-10-23" / f"{clip_id}.opus")
        c = ClipRecord(
            clip_id=clip_id, path=rel, day=date(2026, 10, 23), first_ms=first_ms,
            last_ms=first_ms + 15000, chunk_count=chunks, first_page=1, last_page=2,
            run=1, capture_id=1, opened_with_start_marker=True,
            closed_with_stop_marker=True, clock_suspect=False,
        )
        db.add_clip(c)
        clips.append(c)
    return clips


import dataclasses

from lavalier.config import Config


@pytest.fixture
def cfg():
    return Config()


@pytest.fixture
def clip_at(clip_record):
    def _make(**overrides):
        return dataclasses.replace(clip_record, **overrides)

    return _make


from datetime import datetime, timezone


def T(h, m, s, ms=0) -> int:
    """Local 2026-10-23 timestamp in ms."""
    return int(datetime(2026, 10, 23, h, m, s, ms * 1000).timestamp() * 1000)


@pytest.fixture
def clip(clip_record):
    def _make(first_ms, last_ms, classification="speech"):
        stamp = datetime.fromtimestamp(first_ms / 1000, tz=timezone.utc)
        clip_id = f"clip_{stamp:%Y%m%dT%H%M%S}.{first_ms % 1000:03d}Z"
        return dataclasses.replace(
            clip_record, clip_id=clip_id, path=f"audio/x/{clip_id}.opus",
            day=datetime.fromtimestamp(first_ms / 1000).date(),
            first_ms=first_ms, last_ms=last_ms,
            chunk_count=(last_ms - first_ms) // 20, classification=classification)

    return _make


@pytest.fixture
def clip_rows_spanning_midnight(db, clip):
    c = clip(T(23, 58, 0), T(23, 58, 0) + 7 * 60 * 1000)
    c.day = date(2026, 10, 23)
    db.add_clip(c)
    return c


from lavalier.config import Config
from lavalier.group import rebuild_day
from lavalier.models import EventRecord, Segment, Transcript, Word


def _words(*specs):
    return [Word(s, e, w, p) for s, e, w, p in specs]


def _real_transcript() -> Transcript:
    ws1 = _words((0.0, 0.4, " test", 0.9), (0.4, 0.8, " test", 0.9), (0.8, 1.2, " test", 0.9),
                 (1.2, 1.6, " one", 0.9), (1.6, 2.0, " two", 0.9), (2.0, 2.32, " three", 0.9))
    ws2 = _words((3.96, 4.4, " test", 0.9), (4.4, 4.8, " test", 0.9), (4.8, 5.2, " test", 0.9),
                 (5.2, 5.6, " one", 0.9), (5.6, 6.0, " two", 0.9), (6.0, 6.34, " three", 0.9))
    text = "test test test one two three"
    return Transcript(
        text=f"{text} {text}", language="en", model="mlx-community/whisper-large-v3-turbo",
        segments=[Segment(0.0, 2.32, f" {text}", -0.293, 0.01, ws1),
                  Segment(3.96, 6.34, f" {text}", -0.293, 0.01, ws2)])


def _press(page, ms) -> EventRecord:
    return EventRecord(
        page_index=page, absolute_ms=ms, capture_id=1, type="button",
        payload={"type": "button", "button_event": "BUTTON_SHORT_PRESS",
                 "button_event_absolute_timestamp_ms": ms})


@pytest.fixture
def seeded_2026_10_23_subset(db, clip_record):
    cfg = Config()
    db.add_clip(dataclasses.replace(clip_record, classification=None, transcribed_at=None, mean_db=-27.2))
    db.set_transcript(clip_record.clip_id, _real_transcript(), "speech", T(23, 0, 0))
    for cid, first, db_ in (("clip_20261024T055514.111Z", 1792821314111, -44.2),
                            ("clip_20261024T060125.346Z", 1792821685346, -40.0)):
        db.add_clip(dataclasses.replace(
            clip_record, clip_id=cid, path=f"audio/2026-10-23/{cid}.opus", first_ms=first,
            last_ms=first + 5500, chunk_count=275, first_page=1, last_page=2, run=1,
            classification=None, transcribed_at=None, mean_db=db_))
        db.set_transcript(cid, Transcript("", "en", cfg.whisper_model, []), "noise", T(23, 0, 0))
    db.add_event(_press(7802, 1792821367981))
    db.add_event(_press(7805, 1792821372732))
    rebuild_day(db, date(2026, 10, 23), cfg)


@pytest.fixture
def seeded_bad_clock_day(db, clip_record):
    cfg = Config()
    first = int(datetime(2026, 10, 24, 9, 0, 0).timestamp() * 1000)
    c = dataclasses.replace(clip_record, clip_id="clip_20261024T160000.000Z", day=date(2026, 10, 24),
                            first_ms=first, last_ms=first + 16000, clock_suspect=True,
                            classification=None, transcribed_at=None)
    db.add_clip(c)
    db.set_transcript(c.clip_id, _real_transcript(), "speech", first + 60000)
    rebuild_day(db, date(2026, 10, 24), cfg)


@pytest.fixture
def seeded_orphan_star(db, clip_record):
    cfg = Config()
    db.add_clip(dataclasses.replace(clip_record, classification=None, transcribed_at=None))
    db.set_transcript(clip_record.clip_id, _real_transcript(), "speech", T(23, 0, 0))
    db.add_event(_press(7000, T(22, 50, 0)))
    rebuild_day(db, date(2026, 10, 23), cfg)


@pytest.fixture
def seeded_retention_day(root, db, cfg, clip_record):
    """Four speech-day clips 10 minutes apart: old, starred, fresh, failed."""
    day = date(2026, 10, 23)
    old_at = T(12, 0, 0)
    specs = [("old", T(10, 0, 0), "speech", old_at),
             ("starred", T(10, 10, 0), "speech", old_at),
             ("fresh", T(10, 20, 0), "speech", old_at + 2 * 86_400_000),
             ("failed", T(10, 30, 0), "failed", None)]
    ids = []
    for name, first, classification, transcribed_at in specs:
        clip_id = f"clip_{name}"
        rel = f"audio/{day.isoformat()}/{clip_id}.opus"
        _write_opus(root.audio / day.isoformat() / f"{clip_id}.opus")
        db.add_clip(dataclasses.replace(
            clip_record, clip_id=clip_id, path=rel, day=day, first_ms=first,
            last_ms=first + 15000, classification=None, transcribed_at=None))
        if classification == "failed":
            db.set_transcript(clip_id, Transcript("", "en", cfg.whisper_model, []), "failed", None)
        else:
            db.set_transcript(clip_id, _real_transcript(), classification, transcribed_at)
        ids.append(clip_id)
    db.add_event(_press(1, T(10, 10, 0)))
    rebuild_day(db, day, cfg)
    return tuple(db.clip(i) for i in ids)


@pytest.fixture
def imported_and_decoded_three_clips(root, db):
    """Three clips with real audio on 2026-10-23, 10 minutes apart; the day is dirty."""
    day = date(2026, 10, 23)
    clips = []
    for name, first in (("a", T(10, 0, 0)), ("b", T(10, 10, 0)), ("c", T(10, 20, 0))):
        clip_id = f"clip_{name}"
        rel = f"audio/{day.isoformat()}/{clip_id}.opus"
        _write_opus(root.audio / day.isoformat() / f"{clip_id}.opus")
        c = ClipRecord(
            clip_id=clip_id, path=rel, day=day, first_ms=first, last_ms=first + 15000,
            chunk_count=750, first_page=1, last_page=2, run=1, capture_id=1,
            opened_with_start_marker=True, closed_with_stop_marker=True, clock_suspect=False)
        db.add_clip(c)
        db.set_loudness(clip_id, -44.2 if name == "c" else -27.2, -10.0)  # the real rec0098 / rec0099 levels
        clips.append(c)
    db.mark_day_dirty(day)
    return tuple(clips)


@pytest.fixture
def imported_status_only(root, db, imported_status_only_capture):
    from lavalier.clips import decode_new_pages
    decode_new_pages(db, root, imported_status_only_capture, capture_day=date(2026, 10, 24))
    return imported_status_only_capture


def speech_transcript() -> Transcript:
    return _real_transcript()


def thank_you_transcript() -> Transcript:
    return Transcript("Thank you.", "en", "mlx-community/whisper-large-v3-turbo", [
        Segment(0, 1.88, " Thank you.", -0.953, 0.0, [Word(0, 0.28, "Thank", 0.05), Word(0.28, 1.88, "you.", 0.99)])])


@pytest.fixture
def silent_speech_day(db, clip_record):
    """2026-10-22, whose only clip is classed speech but whose transcript has no words: a day with no lines."""
    day = date(2026, 10, 22)
    first = clip_record.first_ms - 86_400_000
    cid = "clip_20261023T055514.111Z"
    db.add_clip(dataclasses.replace(clip_record, clip_id=cid, path=f"audio/{day}/{cid}.opus", day=day,
                                    first_ms=first, last_ms=first + 16000, classification=None, transcribed_at=None))
    db.set_transcript(cid, Transcript(" ", "en", "m", [Segment(0, 1.0, "  ", -1.0, 0.9, [])]), "speech", first + 1)
    rebuild_day(db, day, Config())
    assert day in db.days_with_speech()
    return day


@pytest.fixture
def snap():
    return DeviceSnapshot(1000, True, "LISTENING", 0, 786, 94, -10, "USB_DISCONNECTED", "1.1.3", 7)


@pytest.fixture
def two_storage_payloads():
    from pendant_client.decode import storage_page_of
    payloads = [
        make_storage_buffer_msg(
            page_index=i, flash_page=make_audio_flash_page(b"\xb8" + b"A" * 39),
            ingest_type=2, session=1, run=1)
        for i in (10, 11)
    ]
    assert [storage_page_of(p).index for p in payloads] == [10, 11]
    return payloads


# --- CLI fixtures for the device commands ---

from click.testing import CliRunner


class CliEnv:
    """CliRunner bound to a tmp state root; `invoke(args)` returns the click result."""

    def __init__(self, root: Paths):
        self.root = root
        self._runner = CliRunner()

    def invoke(self, args):
        from lavalier.cli import main
        return self._runner.invoke(main, args)


def _make_cli_env(tmp_path, monkeypatch, address: str) -> CliEnv:
    from lavalier import cli
    from lavalier.config import Config, save_config

    paths = Paths(tmp_path / "Pendant")
    paths.ensure()
    save_config(Config(pendant_address=address), paths.config)
    monkeypatch.setenv("PENDANT_ROOT", str(paths.root))
    # no real ioreg, no real unmute wait, and a whisper model that counts as cached
    monkeypatch.setattr(cli, "read_ioreg", lambda: "")
    monkeypatch.setattr(cli, "UNMUTE_SETTLE_S", 0)
    hf = tmp_path / "hf"
    (hf / ("models--" + Config().whisper_model.replace("/", "--"))).mkdir(parents=True)
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(hf))
    return CliEnv(paths)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    return _make_cli_env(tmp_path, monkeypatch, "FAKE")


@pytest.fixture
def cli_env_no_address(tmp_path, monkeypatch):
    return _make_cli_env(tmp_path, monkeypatch, "")


@pytest.fixture
def db_at_root(cli_env):
    d = Database(cli_env.root.db)
    d.migrate()
    try:
        yield d
    finally:
        d.close()


from builders import make_audio_flash_page, make_storage_buffer_msg


@pytest.fixture
def storage_payloads():
    return [
        make_storage_buffer_msg(
            page_index=i, flash_page=make_audio_flash_page(b"\xb8" + b"A" * 39),
            ingest_type=2, session=1, run=1)
        for i in (10, 11, 12)
    ]


# --- app process, control server and client fixtures ---

import http.client
import json
import subprocess
import sys

APP_CLOCK_MS = 1_792_821_400_000  # 2026-10-23 evening, US Pacific

_DEFAULT = object()


class Reply:
    """A fully read HTTP response: the connection is closed before the test sees it."""

    def __init__(self, status: int, body: bytes, headers: Optional[dict] = None):
        self.status = status
        self._body = body
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str, default=None):
        return self._headers.get(name.lower(), default)


def _request(server, method: str, route: str, token, origin, body: Optional[bytes] = None) -> Reply:
    headers = {}
    token = server.token if token is _DEFAULT else token
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    if body is None and method in ("POST", "PUT"):
        body = b""
    if body:
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
    try:
        conn.request(method, route, body=body, headers=headers)
        resp = conn.getresponse()
        return Reply(resp.status, resp.read(), dict(resp.getheaders()))
    finally:
        conn.close()


def get(server, route: str, *, token=_DEFAULT, origin=None) -> Reply:
    return _request(server, "GET", route, token, origin)


def post(server, route: str, body=None, *, token=_DEFAULT, origin=None) -> Reply:
    """POST, with a JSON body when one is given (bytes are sent as they are)."""
    data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
    return _request(server, "POST", route, token, origin, data)


def delete(server, route: str, *, token=_DEFAULT, origin=None) -> Reply:
    return _request(server, "DELETE", route, token, origin)


def put(server, route: str, body, *, token=_DEFAULT, origin=None) -> Reply:
    """PUT a JSON body (bytes are sent as they are)."""
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    return _request(server, "PUT", route, token, origin, data)


class FakeAppLike:
    """What the control server forwards to: records every call it receives."""

    def __init__(self, results: Optional[dict] = None):
        self.busy = False
        self.calls: list[tuple[str, str]] = []
        self.results = dict(results or {})

    def snapshot(self) -> dict:
        self.calls.append(("GET", "/api/status"))
        return {"x": 1}

    async def action(self, name: str) -> dict:
        self.calls.append(("POST", f"/api/{name}"))
        return self.results.get(name, {"did": name})


@pytest.fixture
def fake_app():
    return FakeAppLike()


@pytest.fixture
def token_path(tmp_path):
    return tmp_path / ".server.json"


@pytest.fixture
def server(fake_app, token_path):
    from lavalier.server import ControlServer
    s = ControlServer(fake_app, token_path=token_path)
    s.start()
    try:
        yield s
    finally:
        s.stop()


@pytest.fixture
def running_fake_server(cli_env):
    """A real control server with a real token file at the CLI's state root, in front of a recording fake."""
    from lavalier.server import ControlServer
    app = FakeAppLike(results={
        "mute": {"ok": True, "state": "NOT_RECORDING", "error": None},
        "unmute": {"ok": True, "state": "LISTENING", "error": None},
    })
    s = ControlServer(app, token_path=cli_env.root.root / ".server.json")
    s.start()
    try:
        yield app
    finally:
        s.stop()


def _dead_pid() -> int:
    p = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True,
                       check=True)
    return int(p.stdout)


@pytest.fixture
def stale_token_file(cli_env):
    path = cli_env.root.root / ".server.json"
    path.write_text(json.dumps({"port": 9, "token": "stale", "pid": _dead_pid()}))
    path.chmod(0o600)
    return path


@pytest.fixture
def app_env(root):
    """Builds an App on the test root around a FakePendant; never touches Bluetooth or the model."""
    from lavalier.app import App
    from lavalier.config import save_config
    from lavalier.transcribe import FakeTranscriber

    root.ensure()
    save_config(Config(pendant_address="FAKE"), root.config)
    apps = []

    def make(pendant, poll_interval_s: int = 600, transcriber_factory=None):
        from lavalier.lock import SyncLock
        cfg = Config(pendant_address="FAKE", poll_interval_s=poll_interval_s)
        app = App(root, cfg, pendant_factory=lambda cfg: pendant,
                  transcriber_factory=transcriber_factory or (
                      lambda cfg: FakeTranscriber({}, default=speech_transcript())),
                  now_ms=lambda: APP_CLOCK_MS, cdc_present=lambda: False, settle_s=0,
                  # independent of whatever else runs on the host
                  lock=SyncLock(root.root / ".lock", list_processes=lambda: []))
        apps.append(app)
        return app

    yield make
    for a in apps:
        a.close()


@pytest.fixture
def seeded_fully_duplicated_undecoded_capture(root, db, tmp_path):
    """The field's stuck case: capture A decoded pages 1..3; capture B (undecoded, sink file still in
    captures/) holds exactly the same pages under the real instance, so nothing is left to decode."""
    import hashlib
    import shutil
    from pendant_client.decode import iter_messages_from_bin, storage_page_of, write_batch_ingest_request
    from lavalier.pages import page_key
    from lavalier.pipeline import import_and_decode

    def capture(path, ble="test"):
        fps = [make_audio_flash_page(b"\xb8" + b"A" * 39, did_start_recording=i == 1,
                                     absolute_timestamp_ms=T(10, 0, i)) for i in (1, 2, 3)]
        msgs = [make_storage_buffer_msg(page_index=i, flash_page=fp, ingest_type=2, session=1, run=1)
                for i, fp in zip((1, 2, 3), fps)]
        write_batch_ingest_request(messages=msgs, ble_identifier=ble, path=path)
        return path

    import_and_decode(db, root, capture(tmp_path / "earlier.bin"), capture_day=date(2026, 10, 23))
    src = capture(tmp_path / "20261024T055640Z.bin", ble="test-b")  # same pages, different bytes
    root.captures.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    installed = root.captures / f"{sha[:12]}-{src.name}"
    shutil.copyfile(src, installed)
    shutil.copyfile(src, root.captures / src.name)           # the sink the drain left behind
    messages = list(iter_messages_from_bin(installed))
    cid = db.add_capture(str(installed.relative_to(root.root)), sha, len(messages), False)
    for m in messages:
        sp = storage_page_of(m)
        db.add_page(page_key(sp, storage_instance=0xA1B2C3D4E5F60718), cid, sp.session, sp.ingest_type, 0)
    return cid


@pytest.fixture(autouse=True)
def _restore_fork_log_level():
    """The CLI and app quiet the fork's logger for the whole process; a test must not leak that."""
    import logging
    loggers = [logging.getLogger(n) for n in ("pendant_client", "pendant_client.ble", "pendant_client.session")]
    levels = [lg.level for lg in loggers]
    yield
    for lg, level in zip(loggers, levels):
        lg.setLevel(level)


# --- a real App behind a real ControlServer, for the window's routes ---

CLIP = "clip_20261024T055609.085Z"   # the speech clip of seeded_2026_10_23_subset; also in two_clips_with_audio
CONV = "c-20261023-225609"           # its conversation in seeded_2026_10_23_subset


class AppView:
    """The test's handle on the served App. The App's own connection belongs to its loop thread
    (sqlite3 refuses it anywhere else), so `db` here is the test's connection to the same file;
    everything else is the real App."""

    def __init__(self, app, db):
        self._app = app
        self.db = db

    def __getattr__(self, name):
        return getattr(self._app, name)


def _serve_real_app(app, db):
    import asyncio
    import threading
    from lavalier.server import ControlServer
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    srv = ControlServer(app, token_path=app.paths.root / ".server.json", loop=loop)
    srv.start()
    srv.app = AppView(app, db)
    try:
        yield srv
    finally:
        srv.stop()

        async def close():
            app.close()
        asyncio.run_coroutine_threadsafe(close(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
        t.join(10)
        loop.close()


@pytest.fixture
def server_with_fixture(app_env, db, seeded_2026_10_23_subset):
    from fake_pendant import FakePendant
    yield from _serve_real_app(app_env(FakePendant()), db)


@pytest.fixture
def server_with_audio(app_env, db, two_clips_with_audio):
    from fake_pendant import FakePendant
    yield from _serve_real_app(app_env(FakePendant()), db)


import keyring
import keyring.backend
import keyring.errors


class InMemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.store[(service, username)]


class BrokenKeyring(InMemoryKeyring):
    def get_password(self, service, username):
        raise keyring.errors.KeyringError("locked")

    def set_password(self, service, username, password):
        raise keyring.errors.KeyringError("locked")

    def delete_password(self, service, username):
        raise RuntimeError("backend exploded")


@pytest.fixture(autouse=True)
def memory_keyring():
    """An in-memory Keychain for every test; the real one is never touched. Request it by name to
    reach the backend."""
    old = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(old)
