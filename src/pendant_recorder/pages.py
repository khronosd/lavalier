"""Page identity and capture import."""

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pendant_client.decode import StoragePage, iter_messages_from_bin, storage_page_of
from pendant_client.flash_page import parse_flash_page

from pendant_recorder.db import Database
from pendant_recorder.models import PageKey
from pendant_recorder.paths import Paths

log = logging.getLogger(__name__)


def page_key(sp: StoragePage) -> PageKey:
    return PageKey(sp.run, sp.index, hashlib.sha256(sp.flash_page).hexdigest())


@dataclass
class ImportResult:
    capture_id: int
    messages: int
    pages_new: int
    pages_duplicate: int
    new_payloads: list[bytes] = field(default_factory=list)


def _absolute_ms(sp: StoragePage) -> int:
    try:
        return parse_flash_page(sp.flash_page).absolute_timestamp_ms
    except Exception as exc:
        log.warning("cannot parse flash page run=%s index=%s: %s", sp.run, sp.index, exc)
        return 0


def _install_copy(src: Path, dest: Path, sha: str) -> None:
    """Copy src to dest atomically; replace a dest whose content does not match sha."""
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    shutil.copyfile(src, part)
    os.replace(part, dest)


def import_capture(db: Database, paths: Paths, src: Path, *, complete: bool = True) -> ImportResult:
    src = Path(src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    dest = paths.captures / f"{sha[:12]}-{src.name}"
    _install_copy(src, dest, sha)
    messages = list(iter_messages_from_bin(dest))

    pages_new = 0
    pages_duplicate = 0
    new_payloads: list[bytes] = []
    seen_here: set[PageKey] = set()
    # One transaction: a crash leaves no capture row, so the next import starts clean.
    with db.transaction():
        capture_id = db.capture_by_sha(sha)
        already_imported = capture_id is not None
        if capture_id is None:
            capture_id = db.add_capture(str(dest), sha, len(messages), complete)
        for payload in messages:
            sp = storage_page_of(payload)
            if sp is None:
                if not already_imported:
                    new_payloads.append(payload)
                continue
            key = page_key(sp)
            if key in seen_here or db.page_seen(key):
                pages_duplicate += 1
                continue
            seen_here.add(key)
            pages_new += 1
            new_payloads.append(payload)
            db.add_page(key, capture_id, sp.session, sp.ingest_type, _absolute_ms(sp))

    return ImportResult(capture_id, len(messages), pages_new, pages_duplicate, new_payloads)
