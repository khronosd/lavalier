"""The Notion client: a thin wrapper over the official `notion-client` SDK, rate-limited, with safe error text.

Checked 2026-10-24 against notion-client 3.1.0, which sends `Notion-Version: 2025-09-03`: a database holds data
sources (`databases.retrieve` → `data_sources: [{id, name}]`), its schema and rows live on the data source
(`data_sources.retrieve/update/query`), and a row is a page created under `{"type": "data_source_id", ...}`.

The connector owns one callout block per page and only ever writes inside it, to the page's properties, or a
new page; nothing else on a page is deleted, edited or reordered. Errors never carry the token."""

import copy
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable, Optional

from lavalier.connectors.notion_render import BATCH, OWNED_MARKER, property_schema

NOTION_VERSION = "2025-09-03"
NO_TOKEN = "No token saved. Add one in Settings › Connectors."
CANNOT_SEE = "The integration cannot see this database; share it with the integration in Notion"
GONE = "Notion could not find the day's page or block; it may have been deleted"
REFUSED_TOKEN = "The token was refused"
RATE_LIMITED = "Notion is rate-limiting; try again in a minute"
UNAVAILABLE = "Notion is unavailable; try again later"
UNREACHABLE = "Could not reach Notion"
MAX_RETRY_AFTER_S = 60.0

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


def _split(block: dict) -> tuple[dict, list[dict]]:
    """The owned block with at most BATCH children, and the children left to append to it."""
    kind = block["type"]
    children = block[kind].get("children", [])
    head = dict(block)
    head[kind] = dict(block[kind], children=copy.deepcopy(children[:BATCH]))
    return head, children[BATCH:]


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
        fn = self._sdk()
        for part in endpoint.split("."):
            fn = getattr(fn, part)
        for attempt in (0, 1):
            self._space()
            try:
                return fn(**kw)
            except Exception as e:
                if attempt == 0 and _status(e) == 429:
                    self._sleep(_retry_after_s(e))
                    continue
                raise NotionError(_safe_text(e, missing), _status(e)) from None

    def _list(self, block_id: str) -> list[dict]:
        out, cursor = [], None
        while True:
            kw = {"block_id": block_id, "page_size": 100}
            if cursor:
                kw["start_cursor"] = cursor
            page = self._call("blocks.children.list", missing=GONE, **kw)
            out += page.get("results", [])
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                return out

    def _append(self, block_id: str, children: list[dict]) -> list[dict]:
        added = []
        for i in range(0, len(children), BATCH):
            res = self._call("blocks.children.append", missing=GONE, block_id=block_id, children=children[i:i + BATCH])
            added += res.get("results", [])
        return added

    # --- the database

    def check(self, database_id: str) -> DatabaseInfo:
        self._call("users.me")
        db = self._call("databases.retrieve", database_id=database_id)
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
            raise NotionError(f"The database has {names} with another type; rename or change it in Notion")
        schema = property_schema()
        absent = {n: schema[n] for n in info.missing_properties if n in schema}
        if absent:
            self._call("data_sources.update", data_source_id=info.data_source_id, properties=absent)

    def find_day_page(self, info: DatabaseInfo, day: date) -> Optional[str]:
        res = self._call("data_sources.query", data_source_id=info.data_source_id, page_size=1,
                         filter={"property": "Date", "date": {"equals": day.isoformat()}})
        results = res.get("results") or []
        return results[0]["id"] if results else None

    # --- pages

    def create_day_page(self, info: DatabaseInfo, title: str, properties: dict, block: dict) -> tuple[str, str]:
        """A new page holding the owned block; children past the first BATCH are appended to the block."""
        head, rest = _split(block)
        props = {info.title_property: {"title": _text(title)}, **properties}
        page = self._call("pages.create", parent={"type": "data_source_id", "data_source_id": info.data_source_id},
                          properties=props, children=[head])
        page_id = page["id"]
        block_id = self.find_owned_block(page_id)
        if block_id is None:
            raise NotionError("Notion did not keep the block lavalier wrote")
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
        (added, *_) = self._append(page_id, [head])
        self._append(added["id"], rest)
        return added["id"]

    def update_properties(self, page_id: str, properties: dict) -> None:
        self._call("pages.update", missing=GONE, page_id=page_id, properties=properties)

    def page_exists(self, page_id: str) -> bool:
        try:
            page = self._call("pages.retrieve", missing=GONE, page_id=page_id)
        except NotionError as e:
            if e.status == 404:
                return False
            raise
        return not (page.get("archived") or page.get("in_trash"))

    # --- the owned block

    def owned_block_children(self, block_id: str) -> list[dict]:
        return [_normalise(b) for b in self._list(block_id)]

    def replace_children(self, block_id: str, children: list[dict]) -> None:
        """Delete every child of the owned block, then append the new ones in batches of BATCH."""
        for b in self._list(block_id):
            self._call("blocks.delete", missing=GONE, block_id=b["id"])
        self._append(block_id, children)
