"""The Notion export stage: one page per day, rewritten only inside the block the connector owns, and only while
that block still reads as the connector last wrote it."""

import dataclasses
import time
from datetime import date
from typing import Optional

from lavalier.config import Config
from lavalier.connectors.notion import DatabaseInfo, Notion, NotionError
from lavalier.connectors.notion_render import (content_hash, day_blocks, owned_block, page_properties, page_title,
                                               plain_text)
from lavalier.db import Database, ExportRecord
from lavalier.journal import DayView, day_view

CONNECTOR = "notion"
STOPPED = "The block was edited by hand; export stopped for this day"
NOTHING = "Nothing to export"
NO_DATABASE = "No database chosen. Add one in Settings › Connectors."


def _has_speech(view: DayView) -> bool:
    return any(c.lines for c in view.conversations)


def _error(day: date, row: Optional[ExportRecord], message: str, *, wrote: bool) -> ExportRecord:
    """An error row that keeps what is known of the page. Once a write may have started, the stored text and
    hash are dropped: the block may be half rewritten, and that must not later read as a hand edit."""
    if row is None:
        return ExportRecord(day, CONNECTOR, None, None, None, None, None, "error", message)
    if wrote:
        return dataclasses.replace(row, content_hash=None, plain_text=None, state="error", error=message)
    return dataclasses.replace(row, state="error", error=message)


def _with_page(day: date, row: Optional[ExportRecord], page_id: str, block_id: Optional[str]) -> ExportRecord:
    base = row or ExportRecord(day, CONNECTOR, None, None, None, None, None, "error", None)
    return dataclasses.replace(base, page_id=page_id, block_id=block_id)


def export_day(db: Database, cfg: Config, client: Notion, day: date, *, now_ms: int, force: bool = False,
               info: Optional[DatabaseInfo] = None) -> ExportRecord:
    """Export one day; returns the stored row (or, for a day without speech, a transient error record).
    `info` is a DatabaseInfo from an earlier check with its properties in place; without it the database is
    checked and its missing properties added first."""
    row = db.export(day, CONNECTOR)
    if row is not None and row.state == "stopped" and not force:
        return row
    view = day_view(db, day, cfg, now_ms=now_ms)
    if not _has_speech(view):
        return ExportRecord(day, CONNECTOR, None, None, None, None, None, "error", NOTHING)
    children = day_blocks(view, db.insight(day))
    text, h = plain_text(children), content_hash(children)
    if not cfg.notion_database_id:
        rec = _error(day, row, NO_DATABASE, wrote=False)
        db.set_export(rec)
        return rec

    page_id = block_id = None
    wrote = False       # a write may have started: the block can no longer be compared with the stored text
    rewrite = True      # the owned block still needs this run's children
    try:
        if info is None:
            info = client.check(cfg.notion_database_id)
            if info.missing_properties:
                client.ensure_properties(info)
        if row is not None and row.page_id and client.page_exists(row.page_id):
            page_id = row.page_id
            # the stored block is trusted only once verified: a deleted, moved or retyped block is never read or
            # cleared; the page gets its own callout back through the find-or-append path below
            if row.block_id and client.owned_block_ok(row.block_id, page_id):
                block_id = row.block_id
                if row.plain_text is not None and not force:
                    if plain_text(client.owned_block_children(block_id)) != row.plain_text:
                        rec = dataclasses.replace(row, state="stopped", error=STOPPED)
                        db.set_export(rec)
                        return rec
                    if h == row.content_hash and row.state == "done":
                        return row
        if page_id is None:
            page_id = client.find_day_page(info, day)
        if page_id is not None and block_id is None:
            block_id = client.find_owned_block(page_id)
            if block_id is None:
                wrote = True
                block_id = client.add_owned_block(page_id, owned_block(children))
                client.update_properties(page_id, page_properties(view))
                rewrite = False
        if page_id is None:
            wrote = True

            def created(pid: str) -> None:
                nonlocal page_id
                page_id = pid
                db.set_export(_error(day, _with_page(day, row, pid, None), "Export interrupted", wrote=True))

            new_page, block_id = client.create_day_page(info, page_title(day), page_properties(view),
                                                        owned_block(children), on_page=created)
            page_id = new_page
        elif rewrite:
            wrote = True
            client.replace_children(block_id, children)
            client.update_properties(page_id, page_properties(view))
    except NotionError as e:
        if page_id is not None:   # keep the page the day now has, even when this run found or made it
            row = _with_page(day, row, page_id, block_id)
        rec = _error(day, row, str(e), wrote=wrote)
        db.set_export(rec)
        return rec
    rec = ExportRecord(day, CONNECTOR, page_id, block_id, h, text, now_ms, "done", None)
    db.set_export(rec)
    return rec


def days_to_export(db: Database, cfg: Config, days: list[date]) -> list[date]:
    """Of `days`, those with speech that have no row, a row that is not done, or a stored hash that differs
    from the day's current one. A stopped day is never in the list; only "Export again" (force) moves it."""
    now_ms = int(time.time() * 1000)
    out = []
    for day in days:
        row = db.export(day, CONNECTOR)
        if row is not None and row.state == "stopped":
            continue
        view = day_view(db, day, cfg, now_ms=now_ms)
        if not _has_speech(view):
            continue
        if row is None or row.state != "done" or row.content_hash != content_hash(day_blocks(view, db.insight(day))):
            out.append(day)
    return out
