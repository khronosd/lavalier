"""Page identity and capture import."""

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pendant_client.decode import StoragePage, iter_messages_from_bin, storage_page_of
from pendant_client.flash_page import parse_flash_page

from lavalier.db import Database
from lavalier.models import PageKey
from lavalier.paths import Paths

log = logging.getLogger(__name__)


def page_key(sp: StoragePage, *, storage_instance: int = 0) -> PageKey:
    return PageKey(sp.run, sp.index, hashlib.sha256(sp.flash_page).hexdigest(), storage_instance)


@dataclass
class ImportResult:
    capture_id: int
    messages: int
    pages_new: int
    pages_duplicate: int
    new_payloads: list[bytes] = field(default_factory=list)
    path: str = ""  # the installed copy, relative to the state root, as the captures row stores it


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


def _owned_payloads(db: Database, capture_id: int, messages: list[bytes], storage_instance: int) -> list[bytes]:
    """The payloads a decode of this capture needs: its own storage pages, once each, and
    every non-storage message, in stream order (re-read from the stored copy). A page an older
    capture already registered is left out even when this capture owns a row for it (rows an
    exact-instance dedup let in), so only pages new to the store reach the decoder."""
    # Matched as page_seen does: instance 0 on either side is "unknown" and matches any instance.
    owned: dict[tuple[int, int, str], set[int]] = {}
    for k in db.pages_for_capture(capture_id):
        owned.setdefault((k.run, k.index, k.sha256), set()).add(k.storage_instance)
    out: list[bytes] = []
    taken: set[tuple[int, int, str]] = set()
    for payload in messages:
        sp = storage_page_of(payload)
        if sp is None:
            out.append(payload)
            continue
        key = page_key(sp, storage_instance=storage_instance)
        ident = (key.run, key.index, key.sha256)
        instances = owned.get(ident)
        if not instances or ident in taken:
            continue
        if storage_instance == 0 or 0 in instances or storage_instance in instances:
            taken.add(ident)
            if not db.page_owned_earlier(key, capture_id):
                out.append(payload)
    return out


def import_capture(
    db: Database, paths: Paths, src: Path, *, complete: bool = True, storage_instance: int = 0,
) -> ImportResult:
    src = Path(src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    if src.resolve().parent == paths.captures.resolve() and src.name.startswith(f"{sha[:12]}-"):
        dest = paths.captures / src.name  # already the installed copy (a re-decode); never install it a second time
    else:
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
            stored_path = str(dest.relative_to(paths.root))
            capture_id = db.add_capture(stored_path, sha, len(messages), complete)
        else:
            stored_path = db.capture_path(capture_id)
        for payload in messages:
            sp = storage_page_of(payload)
            if sp is None:
                if not already_imported:
                    new_payloads.append(payload)
                continue
            key = page_key(sp, storage_instance=storage_instance)
            if key in seen_here or db.page_seen(key):
                pages_duplicate += 1
                continue
            seen_here.add(key)
            pages_new += 1
            new_payloads.append(payload)
            db.add_page(key, capture_id, sp.session, sp.ingest_type, _absolute_ms(sp))
        if already_imported and not db.capture_decoded(capture_id):
            # An earlier decode failed after this import committed: hand back everything the
            # capture owns so the decode runs again instead of being skipped for good.
            new_payloads = _owned_payloads(db, capture_id, messages, storage_instance)

    return ImportResult(capture_id, len(messages), pages_new, pages_duplicate, new_payloads, stored_path)
