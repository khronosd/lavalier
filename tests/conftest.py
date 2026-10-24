import pytest

from pendant_recorder.paths import Paths


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
