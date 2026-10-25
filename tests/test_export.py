import dataclasses
import re
from datetime import date, datetime
from pathlib import Path

import pytest

import fake_notion as fn
from conftest import speech_transcript
from lavalier.connectors import notion_render as nr
from lavalier.connectors.export import CONNECTOR, NOTHING, STOPPED, days_to_export, export_day
from lavalier.connectors.notion import Notion
from lavalier.group import rebuild_day
from lavalier.insights.schema import FollowUp, Insight
from lavalier.journal import day_view

DAY = date(2026, 10, 23)
EMPTY = date(2026, 10, 21)
NOW = 1_792_900_000_000
SRC = Path(__file__).resolve().parents[1] / "src" / "lavalier" / "connectors"


@pytest.fixture
def ncfg(cfg):
    return dataclasses.replace(cfg, notion_enabled=True, notion_database_id=fn.DATABASE_ID)


@pytest.fixture
def fake():
    return fn.FakeNotionClient()


@pytest.fixture
def client(fake):
    return Notion(fn.SECRET, client=fake, sleep=lambda s: None)


def _insight(db):
    gen = int(datetime(2026, 10, 24, 4, 12).timestamp() * 1000)
    db.set_insight(DAY, provider="anthropic", model="claude-opus-5-5", prompt_version=1, generated_ms=gen,
                   input_chars=100, insight=Insight("A short test.", [FollowUp("Call back", None, None)], [], []))


def _grow_by_a_clip(db, cfg, clip_record):
    first = clip_record.first_ms + 10 * 60_000
    cid = "clip_20261024T060609.085Z"
    db.add_clip(dataclasses.replace(clip_record, clip_id=cid, path=f"audio/2026-10-23/{cid}.opus", first_ms=first,
                                    last_ms=first + 16000, classification=None, transcribed_at=None))
    db.set_transcript(cid, speech_transcript(), "speech", first + 60_000)
    rebuild_day(db, DAY, cfg)


def _owned_text(fake, block_id):
    return nr.plain_text(fake.block_children(block_id))


def _expected(db, cfg):
    return nr.day_blocks(day_view(db, DAY, cfg, now_ms=NOW), db.insight(DAY))


# --- the first export

def test_a_first_export_creates_the_page_with_the_owned_block(db, ncfg, seeded_2026_10_23_subset, fake, client):
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert rec.state == "done" and rec.error is None and rec.connector == CONNECTOR == "notion"
    assert rec == db.export(DAY, "notion")
    children = _expected(db, ncfg)
    assert rec.content_hash == nr.content_hash(children) and rec.plain_text == nr.plain_text(children)
    assert rec.exported_ms == NOW
    (page,) = fake.page_store.values()
    assert rec.page_id == page["id"]
    (callout,) = fake.page_children(rec.page_id)
    assert callout["id"] == rec.block_id and callout["type"] == "callout"
    assert callout["callout"]["rich_text"][0]["text"]["content"] == nr.OWNED_MARKER
    assert _owned_text(fake, rec.block_id) == rec.plain_text
    view = day_view(db, DAY, ncfg, now_ms=NOW)
    assert page["properties"]["Name"]["title"][0]["text"]["content"] == "2026-10-23"
    for k, v in nr.page_properties(view).items():
        assert page["properties"][k] == v
    assert fake.properties.keys() >= set(nr.property_schema())


def test_a_day_without_speech_is_not_exported(db, ncfg, fake, client):
    rec = export_day(db, ncfg, client, EMPTY, now_ms=NOW)
    assert (rec.state, rec.error, rec.page_id) == ("error", NOTHING, None) and NOTHING == "Nothing to export"
    assert db.export(EMPTY, "notion") is None and fake.calls == []


def test_an_unchanged_day_writes_nothing(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    fake.calls.clear()
    again = export_day(db, ncfg, client, DAY, now_ms=NOW + 1000)
    assert again == first and fake.writes() == []


@pytest.mark.parametrize("grow", ["insight", "clip"])
def test_a_grown_day_updates_the_same_page_in_place(grow, db, ncfg, seeded_2026_10_23_subset, clip_record, fake,
                                                     client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    outside = fake.add_owner_block(first.page_id, "my own note")
    if grow == "insight":
        _insight(db)
    else:
        _grow_by_a_clip(db, ncfg, clip_record)
    fake.calls.clear()
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW + 5000)
    assert rec.state == "done" and (rec.page_id, rec.block_id) == (first.page_id, first.block_id)
    assert rec.content_hash != first.content_hash and rec.exported_ms == NOW + 5000
    assert len(fake.page_store) == 1 and "pages.create" not in fake.names()
    assert _owned_text(fake, rec.block_id) == rec.plain_text == nr.plain_text(_expected(db, ncfg))
    assert [b["id"] for b in fake.page_children(rec.page_id)] == [rec.block_id, outside]
    assert fake.block_store[outside]["paragraph"]["rich_text"][0]["text"]["content"] == "my own note"
    view = day_view(db, DAY, ncfg, now_ms=NOW)
    assert fake.page_store[rec.page_id]["properties"]["Speech (min)"] == nr.page_properties(view)["Speech (min)"]
    assert fake.page_store[rec.page_id]["properties"]["Conversations"] == nr.page_properties(view)["Conversations"]
    deleted = {kw["block_id"] for n, kw in fake.calls if n == "blocks.delete"}
    assert deleted and all(fake.block_store[b]["parent"] == rec.block_id for b in deleted)


def test_notes_outside_the_owned_block_do_not_stop_the_export(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    fake.add_owner_block(first.page_id, "a note under it")
    _insight(db)
    assert export_day(db, ncfg, client, DAY, now_ms=NOW).state == "done"


# --- hand edits

def test_a_hand_edited_block_stops_the_export(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    edited = fake.block_children(first.block_id)[1]["id"]
    fake.edit_block_text(edited, "I fixed this line myself")
    _insight(db)                                      # the day changed too: still nothing is written
    fake.calls.clear()
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW + 1)
    assert rec.state == "stopped" and rec.error == STOPPED == "The block was edited by hand; export stopped for this day"
    assert (rec.page_id, rec.block_id, rec.content_hash, rec.plain_text) == (
        first.page_id, first.block_id, first.content_hash, first.plain_text)
    assert db.export(DAY, "notion") == rec
    assert fake.writes() == []
    b = fake.block_store[edited]
    assert b[b["type"]]["rich_text"][0]["text"]["content"] == "I fixed this line myself"
    fake.calls.clear()
    assert export_day(db, ncfg, client, DAY, now_ms=NOW + 2) == rec      # stays stopped, touches nothing
    assert fake.calls == []


def test_an_added_line_inside_the_block_also_stops(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    fake.add_owner_block(first.block_id, "a note inside")
    _insight(db)
    assert export_day(db, ncfg, client, DAY, now_ms=NOW).state == "stopped"


def test_export_again_overwrites_a_stopped_day_once(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    outside = fake.add_owner_block(first.page_id, "my own note")
    fake.edit_block_text(fake.block_children(first.block_id)[0]["id"], "hand edit")
    assert export_day(db, ncfg, client, DAY, now_ms=NOW).state == "stopped"
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW + 9, force=True)
    assert rec.state == "done" and rec.error is None and (rec.page_id, rec.block_id) == (first.page_id, first.block_id)
    assert _owned_text(fake, rec.block_id) == rec.plain_text and "hand edit" not in rec.plain_text
    assert not fake.block_store[outside]["in_trash"] and len(fake.page_store) == 1
    fake.calls.clear()
    assert export_day(db, ncfg, client, DAY, now_ms=NOW + 10) == rec    # resumed: unchanged, nothing written
    assert fake.writes() == []
    fake.edit_block_text(fake.block_children(rec.block_id)[0]["id"], "edited again")
    _insight(db)
    assert export_day(db, ncfg, client, DAY, now_ms=NOW + 11).state == "stopped"   # force was once


def test_force_overwrites_a_hand_edited_done_day_even_when_unchanged(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    fake.edit_block_text(fake.block_children(first.block_id)[0]["id"], "hand edit")
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW, force=True)
    assert rec.state == "done" and _owned_text(fake, rec.block_id) == first.plain_text


# --- pages that went away, rows that went away

def test_a_trashed_page_is_recreated(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    fake.page_store[first.page_id]["in_trash"] = True
    _insight(db)
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert rec.state == "done" and rec.page_id != first.page_id and len(fake.page_store) == 2
    assert not fake.block_store[first.block_id]["in_trash"]       # nothing on the old page was touched


def test_a_lost_row_adopts_the_existing_page(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    db._conn.execute("DELETE FROM exports")
    db._conn.commit()
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert rec.state == "done" and (rec.page_id, rec.block_id) == (first.page_id, first.block_id)
    assert len(fake.page_store) == 1


def test_a_dated_page_without_an_owned_block_gets_one_appended(db, ncfg, seeded_2026_10_23_subset, fake, client):
    client.ensure_properties(client.check(fn.DATABASE_ID))
    theirs = fake.pages.create(parent={"type": "data_source_id", "data_source_id": fn.DATA_SOURCE_ID},
                               properties={"Date": {"date": {"start": "2026-10-23"}}},
                               children=[{"object": "block", "type": "paragraph",
                                          "paragraph": {"rich_text": [{"type": "text", "text": {"content": "mine"}}]}}])
    (mine,) = fake.page_children(theirs["id"])
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert rec.state == "done" and rec.page_id == theirs["id"] and len(fake.page_store) == 1
    assert [b["id"] for b in fake.page_children(rec.page_id)] == [mine["id"], rec.block_id]
    assert fake.block_store[mine["id"]]["paragraph"]["rich_text"][0]["text"]["content"] == "mine"
    assert _owned_text(fake, rec.block_id) == rec.plain_text


# --- failures

def test_a_server_error_is_an_error_row(db, ncfg, seeded_2026_10_23_subset, fake, client):
    fake.fail("pages.create", fn.server_error())
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert (rec.state, rec.error) == ("error", "Notion is unavailable; try again later")
    assert db.export(DAY, "notion") == rec and fn.SECRET not in (rec.error or "")
    assert fake.names().count("pages.create") == 1             # a 5xx is not retried
    again = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert again.state == "done" and len(fake.page_store) == 1


def test_a_timeout_is_an_error_row(db, ncfg, seeded_2026_10_23_subset, fake, client):
    fake.fail("users.me", fn.timeout())
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert (rec.state, rec.error) == ("error", "Could not reach Notion") and fake.writes() == []


def test_a_database_it_cannot_see_is_an_error_row_and_nothing_is_written(db, ncfg, seeded_2026_10_23_subset, fake,
                                                                         client):
    fake.visible = False
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert rec.state == "error" and "cannot see this database" in rec.error and fake.writes() == []


def test_no_token_is_an_error_row(db, ncfg, seeded_2026_10_23_subset):
    rec = export_day(db, ncfg, Notion(None), DAY, now_ms=NOW)
    assert (rec.state, rec.error) == ("error", "No token saved. Add one in Settings › Connectors.")


def test_no_database_is_an_error_row(db, cfg, seeded_2026_10_23_subset, fake, client):
    rec = export_day(db, cfg, client, DAY, now_ms=NOW)
    assert rec.state == "error" and "database" in rec.error.lower() and fake.calls == []


def test_a_failure_mid_rewrite_is_not_mistaken_for_a_hand_edit(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    _insight(db)
    fake.fail("blocks.children.append", fn.server_error())
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert rec.state == "error" and rec.page_id == first.page_id and rec.plain_text is None
    again = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert again.state == "done" and _owned_text(fake, again.block_id) == again.plain_text


def test_a_failed_stopped_day_stays_stopped(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    fake.edit_block_text(fake.block_children(first.block_id)[0]["id"], "hand edit")
    _insight(db)
    assert export_day(db, ncfg, client, DAY, now_ms=NOW).state == "stopped"
    fake.fail("users.me", fn.server_error())
    assert export_day(db, ncfg, client, DAY, now_ms=NOW).state == "stopped"


# --- which days

def test_days_to_export(db, ncfg, seeded_2026_10_23_subset, fake, client):
    assert days_to_export(db, ncfg, [EMPTY, DAY]) == [DAY]              # no row; the empty day never
    export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert days_to_export(db, ncfg, [EMPTY, DAY]) == []                 # unchanged
    _insight(db)
    assert days_to_export(db, ncfg, [DAY]) == [DAY]                     # the hash moved
    rec = db.export(DAY, "notion")
    db.set_export(dataclasses.replace(rec, state="stopped", error=STOPPED))
    assert days_to_export(db, ncfg, [DAY]) == []                        # never a stopped day
    db.set_export(dataclasses.replace(rec, state="error", error="x"))
    export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert days_to_export(db, ncfg, [DAY]) == []
    db.set_export(dataclasses.replace(db.export(DAY, "notion"), state="error", error="x"))
    assert days_to_export(db, ncfg, [DAY]) == [DAY]                     # an error row is retried


# --- the boundary

def test_connectors_never_import_playback_or_audio():
    files = sorted(SRC.rglob("*.py"))
    assert len(files) >= 3
    bad_import = re.compile(r"^\s*(from|import)\s+(lavalier\.playback|lavalier\.audio|subprocess)\b"
                            r"|^\s*from\s+lavalier\s+import\s+.*\b(playback|audio)\b", re.M)
    bad_open = re.compile(r"open\([^)]*audio/")
    for f in files:
        src = f.read_text()
        assert not bad_import.search(src), f
        assert not bad_open.search(src), f
        assert "paths.audio" not in src and ".audio /" not in src, f


# --- fix round 1: the stored block id is verified before any read or delete

def test_a_trashed_callout_gets_a_new_owned_block(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    old_children = {b["id"] for b in fake.block_children(first.block_id)}
    fake.block_store[first.block_id]["in_trash"] = True                  # the owner deleted the callout
    _insight(db)
    fake.calls.clear()
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW + 1)
    assert rec.state == "done" and rec.page_id == first.page_id and rec.block_id != first.block_id
    assert db.export(DAY, "notion").block_id == rec.block_id
    assert [b["id"] for b in fake.page_children(rec.page_id)] == [rec.block_id]
    assert _owned_text(fake, rec.block_id) == rec.plain_text
    deleted = {kw["block_id"] for n, kw in fake.calls if n == "blocks.delete"}
    assert not deleted & (old_children | {first.block_id})
    assert "blocks.children.list" not in [n for n, kw in fake.calls if kw.get("block_id") == first.block_id]


def test_a_block_of_another_type_at_the_stored_id_is_never_deleted(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    theirs = fake.add_owner_block(first.page_id, "my paragraph")
    inner = fake.add_owner_block(theirs, "nested under it")
    db.set_export(dataclasses.replace(db.export(DAY, "notion"), block_id=theirs))
    _insight(db)
    fake.calls.clear()
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert rec.state == "done" and rec.block_id == first.block_id         # found its own callout again
    deleted = {kw["block_id"] for n, kw in fake.calls if n == "blocks.delete"}
    assert theirs not in deleted and inner not in deleted
    assert not fake.block_store[theirs]["in_trash"] and not fake.block_store[inner]["in_trash"]
    assert all(fake.block_store[b]["parent"] == first.block_id for b in deleted)


def test_a_failure_after_the_page_is_created_never_duplicates_it(db, ncfg, seeded_2026_10_23_subset, fake, client):
    fake.fail("blocks.children.list", fn.server_error())                 # reading back the new callout fails
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW)
    (pid,) = fake.page_store
    assert rec.state == "error" and rec.page_id == pid and rec.block_id is None and rec.plain_text is None
    again = export_day(db, ncfg, client, DAY, now_ms=NOW)
    assert again.state == "done" and again.page_id == pid and len(fake.page_store) == 1
    assert _owned_text(fake, again.block_id) == again.plain_text


# --- fix round 2: a transient failure never forgets the ids it did not replace

@pytest.mark.parametrize("err", [fn.server_error, fn.timeout, lambda: fn.rate_limited("0")])
def test_a_transient_block_check_failure_keeps_the_stored_ids(err, db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    _insight(db)
    fake.fail("blocks.retrieve", err(), err())                         # a 429 is retried once, so fail twice
    failed = export_day(db, ncfg, client, DAY, now_ms=NOW + 1)
    assert failed.state == "error"
    assert (failed.page_id, failed.block_id, failed.plain_text, failed.content_hash) == (
        first.page_id, first.block_id, first.plain_text, first.content_hash)
    fake.failures.clear()
    edited = fake.block_children(first.block_id)[0]["id"]
    fake.edit_block_text(edited, "hand edit")
    fake.calls.clear()
    rec = export_day(db, ncfg, client, DAY, now_ms=NOW + 2)
    assert rec.state == "stopped" and rec.block_id == first.block_id and fake.writes() == []
    b = fake.block_store[edited]
    assert b[b["type"]]["rich_text"][0]["text"]["content"] == "hand edit"


def test_a_transient_page_check_failure_keeps_the_stored_ids(db, ncfg, seeded_2026_10_23_subset, fake, client):
    first = export_day(db, ncfg, client, DAY, now_ms=NOW)
    fake.fail("pages.retrieve", fn.server_error())
    failed = export_day(db, ncfg, client, DAY, now_ms=NOW + 1)
    assert failed.state == "error" and (failed.page_id, failed.block_id) == (first.page_id, first.block_id)
