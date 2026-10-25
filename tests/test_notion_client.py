from datetime import date

import pytest

import fake_notion as fn
from lavalier.connectors import notion_render as nr
from lavalier.connectors.notion import NO_TOKEN, DatabaseInfo, Notion, NotionError

DAY = date(2026, 10, 23)
ALL_FOUR = ["Date", "Speech (min)", "Conversations", "Stars"]


class Clock:
    """A fake monotonic clock that the injected sleep advances."""

    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def notion(client, clock=None, min_interval_s=0.34):
    clock = clock or Clock()
    return Notion(fn.SECRET, client=client, min_interval_s=min_interval_s, sleep=clock.sleep, clock=clock.now)


def para(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


# --- no token

@pytest.mark.parametrize("call", [
    lambda n: n.check(fn.DATABASE_ID),
    lambda n: n.ensure_properties(DatabaseInfo(fn.DATABASE_ID, fn.DATA_SOURCE_ID, "J", ["Date"], "Name")),
    lambda n: n.find_day_page(DatabaseInfo(fn.DATABASE_ID, fn.DATA_SOURCE_ID, "J", [], "Name"), DAY),
    lambda n: n.create_day_page(DatabaseInfo(fn.DATABASE_ID, fn.DATA_SOURCE_ID, "J", [], "Name"), "t", {}, nr.owned_block([])),
    lambda n: n.update_properties("p", {}),
    lambda n: n.owned_block_children("b"),
    lambda n: n.replace_children("b", []),
    lambda n: n.page_exists("p"),
])
def test_every_method_without_a_token_says_so(call):
    with pytest.raises(NotionError) as e:
        call(Notion(None))
    assert str(e.value) == NO_TOKEN == "No token saved. Add one in Settings › Connectors."


def test_no_token_never_builds_an_sdk_client(monkeypatch):
    import notion_client
    monkeypatch.setattr(notion_client, "Client", lambda *a, **k: pytest.fail("built a client"))
    with pytest.raises(NotionError):
        Notion("").check(fn.DATABASE_ID)


def test_the_sdk_client_is_built_lazily_without_its_own_retries(monkeypatch):
    import notion_client
    built = []
    monkeypatch.setattr(notion_client, "Client", lambda **k: built.append(k) or fn.FakeNotionClient())
    n = Notion(fn.SECRET, sleep=lambda s: None)
    assert built == []
    n.check(fn.DATABASE_ID)
    assert len(built) == 1 and built[0]["auth"] == fn.SECRET and built[0]["retry"] is False
    assert built[0]["notion_version"] == "2025-09-03"


# --- check

def test_check_reads_the_data_source_title_and_missing_properties():
    c = fn.FakeNotionClient(title="Journal")
    i = notion(c).check(fn.DATABASE_ID)
    assert i == DatabaseInfo(fn.DATABASE_ID, fn.DATA_SOURCE_ID, "Journal", ALL_FOUR, "Name", [])
    assert c.names() == ["users.me", "databases.retrieve", "data_sources.retrieve"]
    assert c.writes() == []


def test_check_names_a_database_the_integration_cannot_see():
    c = fn.FakeNotionClient()
    c.visible = False
    with pytest.raises(NotionError) as e:
        notion(c).check(fn.DATABASE_ID)
    assert str(e.value) == "The integration cannot see this database; share it with the integration in Notion"
    assert c.writes() == []


def test_a_forbidden_database_reads_the_same():
    c = fn.FakeNotionClient()
    c.fail("databases.retrieve", fn.api_error(403, fn.APIErrorCode.RestrictedResource))
    with pytest.raises(NotionError, match="cannot see this database"):
        notion(c).check(fn.DATABASE_ID)


def test_a_wrongly_typed_property_counts_as_missing():
    props = dict(fn.DEFAULT_PROPERTIES, Date={"id": "d", "name": "Date", "type": "rich_text", "rich_text": {}},
                 Stars={"id": "s", "name": "Stars", "type": "number", "number": {"format": "number"}})
    i = notion(fn.FakeNotionClient(properties=props)).check(fn.DATABASE_ID)
    assert i.missing_properties == ["Date", "Speech (min)", "Conversations"]
    assert i.mistyped_properties == ["Date"]


def test_the_title_property_is_read_from_the_schema():
    props = {"Day": {"id": "title", "name": "Day", "type": "title", "title": {}}}
    c = fn.FakeNotionClient(properties=props)
    n = notion(c)
    i = n.check(fn.DATABASE_ID)
    assert i.title_property == "Day"
    n.ensure_properties(i)
    pid, _ = n.create_day_page(n.check(fn.DATABASE_ID), "2026-10-23", {"Stars": {"number": 2}}, nr.owned_block([]))
    props = c.page_store[pid]["properties"]
    assert props["Day"] == {"title": [{"type": "text", "text": {"content": "2026-10-23"}}]}
    assert "Name" not in props and props["Stars"] == {"number": 2}


# --- ensure_properties

def test_missing_properties_are_added_once():
    c = fn.FakeNotionClient()
    n = notion(c)
    n.ensure_properties(n.check(fn.DATABASE_ID))
    updates = [kw for name, kw in c.calls if name == "data_sources.update"]
    assert len(updates) == 1
    assert updates[0]["data_source_id"] == fn.DATA_SOURCE_ID and updates[0]["properties"] == nr.property_schema()
    again = n.check(fn.DATABASE_ID)
    assert again.missing_properties == []
    n.ensure_properties(again)
    assert c.names().count("data_sources.update") == 1


def test_ensure_adds_only_what_is_missing():
    props = dict(fn.DEFAULT_PROPERTIES, Date={"id": "d", "name": "Date", "type": "date", "date": {}})
    c = fn.FakeNotionClient(properties=props)
    n = notion(c)
    n.ensure_properties(n.check(fn.DATABASE_ID))
    (kw,) = [kw for name, kw in c.calls if name == "data_sources.update"]
    assert list(kw["properties"]) == ["Speech (min)", "Conversations", "Stars"]


def test_ensure_never_retypes_the_owners_property():
    props = dict(fn.DEFAULT_PROPERTIES, Date={"id": "d", "name": "Date", "type": "rich_text", "rich_text": {}})
    c = fn.FakeNotionClient(properties=props)
    n = notion(c)
    with pytest.raises(NotionError) as e:
        n.ensure_properties(n.check(fn.DATABASE_ID))
    assert "Date" in str(e.value) and "another type" in str(e.value)
    assert c.writes() == [] and c.properties["Date"]["type"] == "rich_text"


# --- find / create / properties

def test_find_day_page_filters_on_date():
    c = fn.FakeNotionClient()
    n = notion(c)
    i = n.check(fn.DATABASE_ID)
    n.ensure_properties(i)
    assert n.find_day_page(i, DAY) is None
    pid, _ = n.create_day_page(i, "2026-10-23", {"Date": {"date": {"start": "2026-10-23"}}}, nr.owned_block([]))
    assert n.find_day_page(i, DAY) == pid
    assert n.find_day_page(i, date(2026, 10, 24)) is None
    (kw, *_) = [kw for name, kw in c.calls if name == "data_sources.query"]
    assert kw["data_source_id"] == fn.DATA_SOURCE_ID
    assert kw["filter"] == {"property": "Date", "date": {"equals": "2026-10-23"}}


def test_create_day_page_batches_a_long_day_into_the_owned_block():
    c = fn.FakeNotionClient()
    n = notion(c)
    i = n.check(fn.DATABASE_ID)
    children = [para(f"line {k}") for k in range(230)]
    pid, bid = n.create_day_page(i, "2026-10-23", {}, nr.owned_block(children))
    (create,) = [kw for name, kw in c.calls if name == "pages.create"]
    assert create["parent"] == {"type": "data_source_id", "data_source_id": fn.DATA_SOURCE_ID}
    (callout,) = create["children"]
    assert callout["type"] == "callout" and len(callout["callout"]["children"]) == 100
    appends = [kw for name, kw in c.calls if name == "blocks.children.append"]
    assert [a["block_id"] for a in appends] == [bid, bid] and [len(a["children"]) for a in appends] == [100, 30]
    assert [b["id"] for b in c.page_children(pid)] == [bid]
    got = n.owned_block_children(bid)
    assert nr.plain_text(got) == nr.plain_text(children)


def test_update_properties_patches_the_page():
    c = fn.FakeNotionClient()
    n = notion(c)
    pid, _ = n.create_day_page(n.check(fn.DATABASE_ID), "t", {"Stars": {"number": 1}}, nr.owned_block([]))
    n.update_properties(pid, {"Stars": {"number": 3}})
    assert c.page_store[pid]["properties"]["Stars"] == {"number": 3}


def test_page_exists():
    c = fn.FakeNotionClient()
    n = notion(c)
    pid, _ = n.create_day_page(n.check(fn.DATABASE_ID), "t", {}, nr.owned_block([]))
    assert n.page_exists(pid) is True
    assert n.page_exists("page-gone") is False
    c.page_store[pid]["in_trash"] = True
    assert n.page_exists(pid) is False


# --- the owned block's children

def test_owned_block_children_paginates():
    c = fn.FakeNotionClient(list_page_size=7)
    n = notion(c)
    _, bid = n.create_day_page(n.check(fn.DATABASE_ID), "t", {}, nr.owned_block([para(str(k)) for k in range(20)]))
    assert nr.plain_text(n.owned_block_children(bid)) == "\n".join(str(k) for k in range(20))
    lists = [kw for name, kw in c.calls if name == "blocks.children.list" and kw["block_id"] == bid]
    assert len(lists) == 3


def test_owned_block_children_reads_any_rich_text_and_flags_nesting():
    c = fn.FakeNotionClient()
    n = notion(c)
    _, bid = n.create_day_page(n.check(fn.DATABASE_ID), "t", {}, nr.owned_block([para("a"), para("b")]))
    first, second = c.block_children(bid)
    first["paragraph"]["rich_text"] = [{"type": "mention", "mention": {}, "plain_text": "@Sam"}]
    c.add_owner_block(second["id"], "nested note")
    got = n.owned_block_children(bid)
    text = nr.plain_text(got)
    assert text.splitlines()[0] == "@Sam" and text != "a\nb" and len(text.splitlines()) > 2


def test_replace_children_deletes_every_child_and_appends_in_batches():
    c = fn.FakeNotionClient(list_page_size=40)
    n = notion(c)
    pid, bid = n.create_day_page(n.check(fn.DATABASE_ID), "t", {}, nr.owned_block([para(f"old {k}") for k in range(150)]))
    outside = c.add_owner_block(pid, "my own note")
    old_ids = [b["id"] for b in c.block_children(bid)]
    c.calls.clear()
    new = [para(f"new {k}") for k in range(250)]
    n.replace_children(bid, new)
    deleted = [kw["block_id"] for name, kw in c.calls if name == "blocks.delete"]
    assert sorted(deleted) == sorted(old_ids)
    appends = [kw for name, kw in c.calls if name == "blocks.children.append"]
    assert [a["block_id"] for a in appends] == [bid] * 3 and [len(a["children"]) for a in appends] == [100, 100, 50]
    assert nr.plain_text(n.owned_block_children(bid)) == nr.plain_text(new)
    assert [b["id"] for b in c.page_children(pid)] == [bid, outside]
    assert not c.block_store[outside]["in_trash"] and not c.block_store[bid]["in_trash"]


# --- errors, rate limits

@pytest.mark.parametrize("err, text", [
    (fn.unauthorized(), "The token was refused"),
    (fn.server_error(), "Notion is unavailable; try again later"),
    (fn.api_error(500, fn.APIErrorCode.InternalServerError), "Notion is unavailable; try again later"),
    (fn.timeout(), "Could not reach Notion"),
    (fn.api_error(400, fn.APIErrorCode.ValidationError), "Notion refused the request (validation_error)"),
])
def test_failures_map_to_safe_text_without_the_token(err, text):
    c = fn.FakeNotionClient()
    c.fail("users.me", err)
    with pytest.raises(NotionError) as e:
        notion(c).check(fn.DATABASE_ID)
    assert str(e.value) == text
    assert fn.SECRET not in str(e.value) and fn.SECRET not in repr(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_a_transport_failure_is_could_not_reach():
    import httpx
    c = fn.FakeNotionClient()
    c.fail("users.me", httpx.ConnectError(f"dns failed {fn.SECRET}"))
    with pytest.raises(NotionError) as e:
        notion(c).check(fn.DATABASE_ID)
    assert str(e.value) == "Could not reach Notion" and fn.SECRET not in str(e.value)


def test_a_429_waits_then_retries_once():
    c = fn.FakeNotionClient()
    clock = Clock()
    c.fail("users.me", fn.rate_limited("2"))
    i = notion(c, clock).check(fn.DATABASE_ID)
    assert i.title == "Journal"
    assert c.names()[:2] == ["users.me", "users.me"]
    assert 2 in clock.sleeps


def test_a_second_429_gives_up():
    c = fn.FakeNotionClient()
    clock = Clock()
    c.fail("users.me", fn.rate_limited("3"), fn.rate_limited("3"), fn.rate_limited("3"))
    with pytest.raises(NotionError) as e:
        notion(c, clock).check(fn.DATABASE_ID)
    assert str(e.value) == "Notion is rate-limiting; try again in a minute"
    assert c.names() == ["users.me", "users.me"]
    assert clock.sleeps.count(3) == 1


def test_a_429_without_retry_after_waits_one_second():
    c = fn.FakeNotionClient()
    clock = Clock()
    c.fail("users.me", fn.rate_limited(None))
    notion(c, clock, min_interval_s=0).check(fn.DATABASE_ID)
    assert clock.sleeps == [1]


def test_calls_are_spaced_by_the_minimum_interval():
    c = fn.FakeNotionClient()
    clock = Clock()
    c.clock = clock.now
    n = notion(c, clock)
    n.check(fn.DATABASE_ID)
    n.check(fn.DATABASE_ID)
    assert len(c.stamps) == 6 and c.stamps[0] == 100.0          # the first call does not wait
    gaps = [b - a for a, b in zip(c.stamps, c.stamps[1:])]
    assert all(g >= 0.34 - 1e-9 for g in gaps), gaps


def test_the_retry_after_a_429_is_also_spaced():
    c = fn.FakeNotionClient()
    clock = Clock()
    c.clock = clock.now
    c.fail("users.me", fn.rate_limited("0"))
    notion(c, clock).check(fn.DATABASE_ID)
    assert c.stamps[1] - c.stamps[0] >= 0.34 - 1e-9


# --- fix round 1: the owned block is verified, listings are bounded, only SDK failures are mapped

def _page_with_block(c, n):
    return n.create_day_page(n.check(fn.DATABASE_ID), "t", {}, nr.owned_block([para("a")]))


def test_owned_block_ok_accepts_only_the_live_callout_on_its_page():
    c = fn.FakeNotionClient(uuid_ids=True)
    n = notion(c)
    pid, bid = _page_with_block(c, n)
    other_pid, other_bid = _page_with_block(c, n)
    assert pid.count("-") == 4 and len(pid) == 36
    assert n.owned_block_ok(bid, pid) is True
    assert n.owned_block_ok(bid, pid.replace("-", "")) is True          # a stored id without dashes still matches
    assert n.owned_block_ok(bid, pid.upper()) is True
    assert n.owned_block_ok(other_bid, pid) is False                     # another page's callout
    mine = c.add_owner_block(pid, "a paragraph")
    assert n.owned_block_ok(mine, pid) is False                          # not a callout
    c.edit_block_text(bid, "a callout of my own")
    assert n.owned_block_ok(bid, pid) is False                           # no marker
    assert n.owned_block_ok(other_bid, other_pid) is True
    c.block_store[other_bid]["in_trash"] = True
    assert n.owned_block_ok(other_bid, other_pid) is False               # in the trash
    assert n.owned_block_ok("block-gone", pid) is False                  # 404
    assert c.writes().count("blocks.delete") == 0


def test_owned_block_ok_raises_other_failures():
    c = fn.FakeNotionClient()
    n = notion(c)
    pid, bid = _page_with_block(c, n)
    c.fail("blocks.retrieve", fn.server_error())
    with pytest.raises(NotionError, match="unavailable"):
        n.owned_block_ok(bid, pid)


def test_a_listing_longer_than_the_cap_is_an_error_not_a_truncation():
    from lavalier.connectors.notion import MAX_LIST_PAGES
    c = fn.FakeNotionClient(list_page_size=1)
    n = notion(c)
    _, bid = n.create_day_page(n.check(fn.DATABASE_ID), "t", {}, nr.owned_block([para(str(k)) for k in range(MAX_LIST_PAGES + 5)]))
    c.calls.clear()
    with pytest.raises(NotionError, match="too many blocks"):
        n.owned_block_children(bid)
    assert c.names().count("blocks.children.list") == MAX_LIST_PAGES


def test_a_repeated_cursor_stops_the_listing():
    c = fn.FakeNotionClient()
    n = notion(c)
    calls = []
    c.blocks.children.list = lambda **kw: calls.append(kw) or {"results": [], "has_more": True, "next_cursor": "same"}
    with pytest.raises(NotionError, match="too many blocks"):
        n.owned_block_children("b")
    assert len(calls) == 2


def test_a_programming_error_is_not_dressed_up_as_a_notion_error():
    c = fn.FakeNotionClient()
    c.fail("users.me", KeyError("results"))
    with pytest.raises(KeyError):
        notion(c).check(fn.DATABASE_ID)


def test_add_owned_block_with_an_empty_append_result_is_an_error():
    c = fn.FakeNotionClient()
    n = notion(c)
    pid, _ = _page_with_block(c, n)
    c.blocks.children.append = lambda **kw: {"object": "list", "results": []}
    with pytest.raises(NotionError, match="did not keep"):
        n.add_owned_block(pid, nr.owned_block([para("x")]))


def test_create_day_page_reports_the_page_as_soon_as_it_exists():
    c = fn.FakeNotionClient()
    n = notion(c)
    i = n.check(fn.DATABASE_ID)
    got = []
    c.fail("blocks.children.list", fn.server_error())
    with pytest.raises(NotionError):
        n.create_day_page(i, "t", {}, nr.owned_block([para("a")]), on_page=got.append)
    assert got == list(c.page_store)
