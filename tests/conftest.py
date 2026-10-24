import os
import time

import pytest

from pendant_recorder.paths import Paths


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


@pytest.fixture
def root(tmp_path):
    return Paths(tmp_path / "Pendant")


from datetime import date

from pendant_recorder.db import Database
from pendant_recorder.models import ClipRecord


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
from pendant_recorder.pages import import_capture


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
