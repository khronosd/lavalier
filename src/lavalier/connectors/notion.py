"""The Notion client: a thin wrapper over the official `notion-client` SDK, rate-limited, with safe error text.

Checked 2026-10-24 against notion-client 3.1.0, which sends `Notion-Version: 2025-09-03`: a database holds data
sources (`databases.retrieve` → `data_sources: [{id, name}]`), its schema and rows live on the data source
(`data_sources.retrieve/update/query`), and a row is a page created under `{"type": "data_source_id", ...}`.

The connector owns one callout block per page and only ever writes inside it, to the page's properties, or a
new page; nothing else on a page is deleted, edited or reordered. Errors never carry the token."""

import copy
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable, Optional

from lavalier.connectors.notion_render import BATCH, BATCH_BYTES, OWNED_MARKER, page_title, property_schema

NOTION_VERSION = "2025-09-03"
NO_TOKEN = "No token saved. Add one in Settings › Connectors."
CANNOT_SEE = "The integration cannot see this database; share it with the integration in Notion"
MISTYPED = "Rename or retype these properties in Notion first: "   # the window says the same (connectors.ts)
PAGE_LINK = "Open the database itself and copy its link; a page link does not work here."
GONE = "Notion could not find the day's page or block; it may have been deleted"
REFUSED_TOKEN = "The token was refused"
RATE_LIMITED = "Notion is rate-limiting; try again in a minute"
UNAVAILABLE = "Notion is unavailable; try again later"
UNREACHABLE = "Could not reach Notion"
MAX_RETRY_AFTER_S = 60.0
MAX_LIST_PAGES = 50         # of 100 blocks each; a longer listing is an error, never a silent truncation
TOO_MANY = "The page or block has too many blocks to read"
NOT_KEPT = "Notion did not keep the block lavalier wrote"

log = logging.getLogger("lavalier.notion")


class NotionError(RuntimeError):
    """Safe text for the owner; never the token. `status` is the HTTP status when Notion answered."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class DatabaseInfo:
    database_id: str
    data_source_id: str
    title: str
    missing_properties: list[str]      # of property_schema(): absent, or present with another type
    title_property: str                # the data source's title property ("Name" is only the usual default)
    mistyped_properties: list[str] = field(default_factory=list)   # the subset present with another type


def _status(e: BaseException) -> Optional[int]:
    from notion_client.errors import HTTPResponseError

    return e.status if isinstance(e, HTTPResponseError) else None


def _retry_after_s(e: BaseException) -> float:
    try:
        return min(max(float(e.headers.get("retry-after")), 0.0), MAX_RETRY_AFTER_S)
    except (AttributeError, TypeError, ValueError):
        return 1.0


def _safe_text(e: BaseException, missing: str) -> str:
    """Text safe to show the owner for an SDK or transport failure: fixed sentences and the API's error code."""
    from notion_client.errors import APIResponseError, RequestTimeoutError

    if isinstance(e, RequestTimeoutError):
        return UNREACHABLE
    status = _status(e)
    if status is None:
        return UNREACHABLE
    if status == 401:
        return REFUSED_TOKEN
    if status in (403, 404):
        return missing
    if status == 429:
        return RATE_LIMITED
    if status >= 500:
        return UNAVAILABLE
    if isinstance(e, APIResponseError):
        code = e.code.value if isinstance(e.code, Enum) else str(e.code)
        return f"Notion refused the request ({code})"
    return f"Notion refused the request (HTTP {status})"


def _text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": content}}]


def _joined(rich_text: list[dict]) -> str:
    return "".join(r["text"]["content"] if r.get("type") == "text" and "text" in r else r.get("plain_text", "")
                   for r in rich_text or [])


def _bare(notion_id) -> str:
    """An id without dashes, lower case: Notion writes the same id with and without them."""
    return str(notion_id or "").replace("-", "").lower()


def _normalise(block: dict) -> dict:
    """A block as Notion returns it, reduced to what notion_render.plain_text reads: any rich text (mentions,
    equations) becomes its text; a block without rich text reads as its type; nested blocks add a line, since
    the blocks the connector writes never have any."""
    kind = block.get("type") or "unsupported"
    body = block.get(kind) or {}
    content = _joined(body["rich_text"]) if "rich_text" in body else f"[{kind}]"
    out = {"object": "block", "type": kind, kind: {"rich_text": _text(content)}}
    if block.get("has_children"):
        out[kind]["children"] = [{"object": "block", "type": "paragraph",
                                  "paragraph": {"rich_text": _text("[nested blocks]")}}]
    return out


def _size(value) -> int:
    return len(json.dumps(value).encode())


def _first_batch(children: list[dict], budget: int = BATCH_BYTES) -> int:
    """How many of `children` go in one request: at most BATCH, and at most `budget` bytes of JSON as a list
    (json.dumps writes "[a, b]": two brackets and two bytes between items). A single child over the budget
    still goes alone; Notion then refuses it with its own error."""
    size = 2
    for k, child in enumerate(children[:BATCH]):
        size += _size(child) + (2 if k else 0)
        if k and size > budget:
            return k
    return min(len(children), BATCH)


def _batches(children: list[dict]) -> list[list[dict]]:
    out = []
    while children:
        k = _first_batch(children)
        out.append(children[:k])
        children = children[k:]
    return out


def _split(block: dict) -> tuple[dict, list[dict]]:
    """The owned block with the children that fit one request beside it, and the children left to append."""
    kind = block["type"]
    children = block[kind].get("children", [])
    bare = dict(block)
    bare[kind] = dict(block[kind], children=[])
    k = _first_batch(children, BATCH_BYTES - _size([bare]))
    head = dict(block)
    head[kind] = dict(block[kind], children=copy.deepcopy(children[:k]))
    return head, children[k:]


class Notion:
    def __init__(self, token: Optional[str], *, client=None, min_interval_s: float = 0.34,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self._token = token or None
        self._client = client
        self.min_interval_s = min_interval_s
        self._sleep = sleep
        self._clock = clock
        self._last: Optional[float] = None

    # --- the one door to the SDK

    def _sdk(self):
        if self._token is None:
            raise NotionError(NO_TOKEN)
        if self._client is None:
            import notion_client

            # the SDK's own retries are off: _call retries a 429 once and nothing else
            self._client = notion_client.Client(auth=self._token, notion_version=NOTION_VERSION, retry=False,
                                                timeout_ms=30_000, logger=log)
        return self._client

    def _space(self) -> None:
        if self._last is not None:
            wait = self._last + self.min_interval_s - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def _call(self, endpoint: str, *, missing: str = CANNOT_SEE, **kw):
        import httpx
        from notion_client.errors import NotionClientErrorBase

        fn = self._sdk()
        for part in endpoint.split("."):
            fn = getattr(fn, part)
        for attempt in (0, 1):
            self._space()
            try:
                return fn(**kw)
            except (NotionClientErrorBase, httpx.HTTPError) as e:   # anything else is a bug and propagates
                if attempt == 0 and _status(e) == 429:
                    self._sleep(_retry_after_s(e))
                    continue
                raise NotionError(_safe_text(e, missing), _status(e)) from None

    def _list(self, block_id: str) -> list[dict]:
        out, cursor, seen = [], None, set()
        for _ in range(MAX_LIST_PAGES):
            kw = {"block_id": block_id, "page_size": 100}
            if cursor:
                kw["start_cursor"] = cursor
            page = self._call("blocks.children.list", missing=GONE, **kw)
            out += page.get("results", [])
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                return out
            if cursor in seen:
                break
            seen.add(cursor)
        raise NotionError(TOO_MANY)

    def _append(self, block_id: str, children: list[dict]) -> list[dict]:
        added = []
        for batch in _batches(children):
            res = self._call("blocks.children.append", missing=GONE, block_id=block_id, children=batch)
            added += res.get("results", [])
        return added

    # --- the database

    def check(self, database_id: str) -> DatabaseInfo:
        self._call("users.me")
        try:
            db = self._call("databases.retrieve", database_id=database_id)
        except NotionError as e:
            # a page's id (or anything else that is not a database) is a validation error; a database the
            # integration was not given reads as not found, and so does a page it cannot see
            if e.status == 400:
                raise NotionError(PAGE_LINK, 400) from None
            if e.status == 404:
                raise NotionError(f"{CANNOT_SEE}. {PAGE_LINK}", 404) from None
            raise
        sources = db.get("data_sources") or []
        if not sources:
            raise NotionError("This database has no data source to write to")
        ds_id = sources[0]["id"]   # a database with several data sources: the first one, as Notion lists them
        ds = self._call("data_sources.retrieve", data_source_id=ds_id)
        props = ds.get("properties") or {}
        title_prop = next((name for name, p in props.items() if p.get("type") == "title"), "Name")
        missing, mistyped = [], []
        for name, spec in property_schema().items():
            have = props.get(name)
            if have is None or have.get("type") != next(iter(spec)):
                missing.append(name)
                if have is not None:
                    mistyped.append(name)
        return DatabaseInfo(database_id, ds_id, _joined(db.get("title") or []), missing, title_prop, mistyped)

    def ensure_properties(self, info: DatabaseInfo) -> None:
        """Add the connector's properties that are absent, in one update. A property of the same name with
        another type is the owner's: it is never retyped, and the export cannot start until it is renamed."""
        self._sdk()
        if info.mistyped_properties:
            names = ", ".join(info.mistyped_properties)
            raise NotionError(f"{MISTYPED}{names}")
        schema = property_schema()
        absent = {n: schema[n] for n in info.missing_properties if n in schema}
        if absent:
            self._call("data_sources.update", data_source_id=info.data_source_id, properties=absent)

    def find_day_page(self, info: DatabaseInfo, day: date) -> Optional[str]:
        """The day's page: Date equal to the day and titled with its ISO date, so a page of the owner's that
        only shares the date is never adopted."""
        iso = day.isoformat()
        res = self._call("data_sources.query", data_source_id=info.data_source_id, page_size=1,
                         filter={"and": [{"property": "Date", "date": {"equals": iso}},
                                         {"property": info.title_property, "title": {"equals": page_title(day)}}]})
        results = res.get("results") or []
        return results[0]["id"] if results else None

    # --- pages

    def create_day_page(self, info: DatabaseInfo, title: str, properties: dict, block: dict, *,
                        on_page: Optional[Callable[[str], None]] = None) -> tuple[str, str]:
        """A new page holding the owned block; children past the first batch are appended to the block.
        `on_page` hears the page id the moment the page exists, so a later failure cannot lead to a second page."""
        head, rest = _split(block)
        props = {info.title_property: {"title": _text(title)}, **properties}
        page = self._call("pages.create", parent={"type": "data_source_id", "data_source_id": info.data_source_id},
                          properties=props, children=[head])
        page_id = page["id"]
        if on_page is not None:
            on_page(page_id)
        block_id = self.find_owned_block(page_id)
        if block_id is None:
            raise NotionError(NOT_KEPT)
        self._append(block_id, rest)
        return page_id, block_id

    def find_owned_block(self, page_id: str) -> Optional[str]:
        """The id of the connector's callout among the page's top-level blocks."""
        for b in self._list(page_id):
            if b.get("type") == "callout" and _joined((b.get("callout") or {}).get("rich_text")) == OWNED_MARKER:
                return b["id"]
        return None

    def add_owned_block(self, page_id: str, block: dict) -> str:
        """Append the owned block at the end of an existing page; nothing already on it is touched."""
        head, rest = _split(block)
        added = self._append(page_id, [head])
        if not added or not added[0].get("id"):
            raise NotionError(NOT_KEPT)
        self._append(added[0]["id"], rest)
        return added[0]["id"]

    def owned_block_ok(self, block_id: str, page_id: str) -> bool:
        """True only for the connector's live callout directly on `page_id`: the right type, the marker as its
        text, not archived or in the trash. Checked before the stage reads or deletes anything under a stored id."""
        try:
            b = self._call("blocks.retrieve", missing=GONE, block_id=block_id)
        except NotionError as e:
            if e.status == 404:
                return False
            raise
        parent = b.get("parent") or {}
        return (b.get("type") == "callout" and not b.get("archived") and not b.get("in_trash")
                and _joined((b.get("callout") or {}).get("rich_text")) == OWNED_MARKER
                and parent.get("type") == "page_id" and _bare(parent.get("page_id")) == _bare(page_id))

    def update_properties(self, page_id: str, properties: dict) -> None:
        self._call("pages.update", missing=GONE, page_id=page_id, properties=properties)

    def page_exists(self, page_id: str, info: DatabaseInfo) -> bool:
        """True only for a live page whose parent is the chosen data source (or, on the legacy shape that
        names only a database, the chosen database): a page moved elsewhere counts as no page."""
        try:
            page = self._call("pages.retrieve", missing=GONE, page_id=page_id)
        except NotionError as e:
            if e.status == 404:
                return False
            raise
        if page.get("archived") or page.get("in_trash"):
            return False
        parent = page.get("parent") or {}
        if parent.get("type") == "data_source_id":
            return _bare(parent.get("data_source_id")) == _bare(info.data_source_id)
        if parent.get("type") == "database_id":
            return _bare(parent.get("database_id")) == _bare(info.database_id)
        return False

    # --- the owned block

    def owned_block_children(self, block_id: str) -> list[dict]:
        return [_normalise(b) for b in self._list(block_id)]

    def replace_children(self, block_id: str, children: list[dict]) -> None:
        """Delete every child of the owned block, then append the new ones in batches (by count and size)."""
        for b in self._list(block_id):
            self._call("blocks.delete", missing=GONE, block_id=b["id"])
        self._append(block_id, children)
