"""Capture sink: every payload is on disk before the next one is requested (and so before the ack)."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.protobuf.message import DecodeError
from pendant_client.decode import BatchIngestWriter, storage_page_of

from lavalier.paths import Paths

# the name every sink gives its file; an import installs a copy under another name
SINK_NAME = re.compile(r"^\d{8}T\d{6}Z\.bin$")
_OPEN: set[Path] = set()  # sinks of this process still being written


def open_sink_paths() -> frozenset[Path]:
    return frozenset(_OPEN)


@dataclass(frozen=True)
class CaptureFile:
    path: Path
    messages: int
    pages: int
    first_page: Optional[int]
    last_page: Optional[int]
    complete: bool


class CaptureSink:
    def __init__(self, paths: Paths, *, ble_identifier: str, fsync_every: int, started_ms: int):
        stamp = datetime.fromtimestamp(started_ms / 1000, tz=timezone.utc)
        self.path = paths.captures / f"{stamp:%Y%m%dT%H%M%SZ}.bin"
        self._ble_identifier = ble_identifier
        self._fsync_every = fsync_every
        self._writer: Optional[BatchIngestWriter] = None
        self._messages = 0
        self._pages = 0
        self._first: Optional[int] = None
        self._last: Optional[int] = None

    def add(self, payload: bytes) -> None:
        if self._writer is None:
            self._writer = BatchIngestWriter(
                self.path, ble_identifier=self._ble_identifier, fsync_every=self._fsync_every)
            _OPEN.add(self.path)
        self._writer.add(payload)
        self._messages += 1
        try:
            page = storage_page_of(payload)
        except DecodeError:
            page = None  # an odd payload is kept on disk and counted, not a reason to stop the drain
        if page is not None:
            self._pages += 1
            if self._first is None:
                self._first = page.index
            self._last = page.index

    def close(self, *, complete: bool) -> Optional[CaptureFile]:
        if self._writer is None:
            return None
        try:
            self._writer.close()
        finally:
            _OPEN.discard(self.path)
        return CaptureFile(self.path, self._messages, self._pages, self._first, self._last, complete)
