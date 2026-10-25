"""An in-memory fake of the notion-client SDK surface the connector uses (API version 2025-09-03: databases
hold data sources). Records every call; `fail(name, *errors)` scripts the next calls of one endpoint to raise."""

import copy
import itertools
from types import SimpleNamespace
from typing import Optional

import httpx
from notion_client.errors import APIErrorCode, APIResponseError, RequestTimeoutError

DATABASE_ID = "0123456789abcdef0123456789abcdef"
DATA_SOURCE_ID = "ds-0001"
SECRET = "ntn_secret_token_value"


def api_error(status: int, code: APIErrorCode, *, message: Optional[str] = None,
              retry_after: Optional[str] = None) -> APIResponseError:
    headers = httpx.Headers({"retry-after": retry_after} if retry_after is not None else {})
    # the message deliberately carries the token: a NotionError must never repeat it
    return APIResponseError(code=code, status=status, message=message or f"boom {SECRET}", headers=headers,
                            raw_body_text=f'{{"message": "boom {SECRET}"}}')


def rate_limited(retry_after: Optional[str] = "2") -> APIResponseError:
    return api_error(429, APIErrorCode.RateLimited, retry_after=retry_after)


def server_error() -> APIResponseError:
    return api_error(503, APIErrorCode.ServiceUnavailable)


def not_found() -> APIResponseError:
    return api_error(404, APIErrorCode.ObjectNotFound)


def unauthorized() -> APIResponseError:
    return api_error(401, APIErrorCode.Unauthorized)


def timeout() -> RequestTimeoutError:
    return RequestTimeoutError()


def _text(content: str) -> dict:
    return {"type": "text", "text": {"content": content, "link": None}, "plain_text": content, "href": None,
            "annotations": {}}


DEFAULT_PROPERTIES = {"Name": {"id": "title", "name": "Name", "type": "title", "title": {}}}


class FakeNotionClient:
    def __init__(self, *, properties: Optional[dict] = None, title: str = "Journal", list_page_size: int = 100,
                 uuid_ids: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.clock = None                     # set to a callable to timestamp every call into `stamps`
        self.stamps: list[float] = []
        self.failures: dict[str, list[BaseException]] = {}
        self.list_page_size = list_page_size
        self.uuid_ids = uuid_ids              # ids in Notion's dashed UUID form instead of "page-0001"
        self.visible = True
        self.databases_store = {DATABASE_ID: {"object": "database", "id": DATABASE_ID,
                                              "title": [_text(title)],
                                              "data_sources": [{"id": DATA_SOURCE_ID, "name": title}]}}
        self.properties = copy.deepcopy(properties if properties is not None else DEFAULT_PROPERTIES)
        self.page_store: dict[str, dict] = {}
        self.block_store: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self.users = SimpleNamespace(me=self._wrap("users.me", self._me))
        self.databases = SimpleNamespace(retrieve=self._wrap("databases.retrieve", self._db_retrieve))
        self.data_sources = SimpleNamespace(retrieve=self._wrap("data_sources.retrieve", self._ds_retrieve),
                                            update=self._wrap("data_sources.update", self._ds_update),
                                            query=self._wrap("data_sources.query", self._ds_query))
        self.pages = SimpleNamespace(create=self._wrap("pages.create", self._page_create),
                                        retrieve=self._wrap("pages.retrieve", self._page_retrieve),
                                        update=self._wrap("pages.update", self._page_update))
        children = SimpleNamespace(list=self._wrap("blocks.children.list", self._children_list),
                                   append=self._wrap("blocks.children.append", self._children_append))
        self.blocks = SimpleNamespace(children=children, delete=self._wrap("blocks.delete", self._block_delete),
                                      retrieve=self._wrap("blocks.retrieve", self._block_retrieve))

    # --- scripting and inspection

    def fail(self, name: str, *errors: BaseException) -> None:
        self.failures.setdefault(name, []).extend(errors)

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def writes(self) -> list[str]:
        reads = {"users.me", "databases.retrieve", "data_sources.retrieve", "data_sources.query",
                 "pages.retrieve", "blocks.children.list", "blocks.retrieve"}
        return [n for n in self.names() if n not in reads]

    def page_children(self, page_id: str) -> list[dict]:
        return [self.block_store[i] for i in self.page_store[page_id]["children"] if not self.block_store[i]["in_trash"]]

    def block_children(self, block_id: str) -> list[dict]:
        return [self.block_store[i] for i in self.block_store[block_id]["children"] if not self.block_store[i]["in_trash"]]

    def add_owner_block(self, parent_id: str, text: str) -> str:
        """A block the owner typed on the page (or inside the owned block)."""
        return self._store_block(parent_id, {"object": "block", "type": "paragraph",
                                             "paragraph": {"rich_text": [_text(text)]}})

    def edit_block_text(self, block_id: str, text: str) -> None:
        b = self.block_store[block_id]
        b[b["type"]]["rich_text"] = [_text(text)]

    # --- internals

    def _wrap(self, name, fn):
        def call(*args, **kw):
            self.calls.append((name, dict(kw, _args=args) if args else dict(kw)))
            if self.clock is not None:
                self.stamps.append(self.clock())
            queue = self.failures.get(name)
            if queue:
                raise queue.pop(0)
            return fn(*args, **kw)
        return call

    def _new_id(self, prefix: str) -> str:
        n = next(self._ids)
        if self.uuid_ids:
            return f"{n:08x}-0000-4000-8000-{n:012x}"
        return f"{prefix}-{n:04d}"

    def _parent_children(self, parent_id: str) -> list:
        if parent_id in self.page_store:
            return self.page_store[parent_id]["children"]
        if parent_id in self.block_store and not self.block_store[parent_id]["in_trash"]:
            return self.block_store[parent_id]["children"]
        raise not_found()

    def _store_block(self, parent_id: str, block: dict) -> str:
        block = copy.deepcopy(block)
        bid = self._new_id("block")
        kind = block["type"]
        body = block[kind]
        nested = body.pop("children", [])
        if len(nested) > 100:
            raise api_error(400, APIErrorCode.ValidationError, message="children length should be ≤ 100")
        body["rich_text"] = [_text(r["text"]["content"]) for r in body.get("rich_text", [])]
        self.block_store[bid] = {"object": "block", "id": bid, "type": kind, kind: body, "children": [],
                            "in_trash": False, "parent": parent_id}
        self._parent_children(parent_id).append(bid)
        for child in nested:
            self._store_block(bid, child)
        return bid

    def _public(self, bid: str) -> dict:
        b = self.block_store[bid]
        out = {k: copy.deepcopy(v) for k, v in b.items() if k not in ("children", "parent")}
        out["has_children"] = any(not self.block_store[c]["in_trash"] for c in b["children"])
        return out

    def _me(self, **kw):
        return {"object": "user", "id": "bot-1", "type": "bot"}

    def _db_retrieve(self, database_id=None, **kw):
        if not self.visible or database_id not in self.databases_store:
            raise not_found()
        return copy.deepcopy(self.databases_store[database_id])

    def _ds_retrieve(self, data_source_id=None, **kw):
        if not self.visible or data_source_id != DATA_SOURCE_ID:
            raise not_found()
        return {"object": "data_source", "id": DATA_SOURCE_ID, "properties": copy.deepcopy(self.properties)}

    def _ds_update(self, data_source_id=None, properties=None, **kw):
        for name, spec in (properties or {}).items():
            kind = next(iter(spec))
            self.properties[name] = {"id": self._new_id("prop"), "name": name, "type": kind, kind: spec[kind]}
        return {"object": "data_source", "id": data_source_id}

    @staticmethod
    def _matches(page: dict, flt: dict) -> bool:
        """The filters the connector sends: `and`, a date `equals` and a title `equals`."""
        if "and" in flt:
            return all(FakeNotionClient._matches(page, f) for f in flt["and"])
        value = page["properties"].get(flt["property"]) or {}
        if "date" in flt:
            return (value.get("date") or {}).get("start") == flt["date"]["equals"]
        if "title" in flt:
            return "".join(r["text"]["content"] for r in value.get("title") or []) == flt["title"]["equals"]
        raise AssertionError(f"unexpected filter {flt}")

    def _ds_query(self, data_source_id=None, filter=None, page_size=100, start_cursor=None, **kw):
        hits = [p for p in self.page_store.values() if not p["in_trash"]
                and p["parent"].get("data_source_id") == data_source_id and self._matches(p, filter)]
        return {"object": "list", "results": [{"object": "page", "id": p["id"]} for p in hits][:page_size],
                "has_more": False, "next_cursor": None}

    def _page_create(self, parent=None, properties=None, children=None, **kw):
        assert parent == {"type": "data_source_id", "data_source_id": DATA_SOURCE_ID}, parent
        if len(children or []) > 100:
            raise api_error(400, APIErrorCode.ValidationError, message="children length should be ≤ 100")
        pid = self._new_id("page")
        self.page_store[pid] = {"object": "page", "id": pid, "parent": parent, "properties": copy.deepcopy(properties),
                           "children": [], "in_trash": False, "archived": False}
        for child in children or []:
            self._store_block(pid, child)
        return {"object": "page", "id": pid}

    def _page_retrieve(self, page_id=None, **kw):
        if page_id not in self.page_store:
            raise not_found()
        p = self.page_store[page_id]
        return {"object": "page", "id": page_id, "in_trash": p["in_trash"], "archived": p["archived"],
                "parent": copy.deepcopy(p["parent"]), "properties": copy.deepcopy(p["properties"])}

    def _page_update(self, page_id=None, properties=None, **kw):
        if page_id not in self.page_store:
            raise not_found()
        self.page_store[page_id]["properties"].update(copy.deepcopy(properties or {}))
        return {"object": "page", "id": page_id}

    def _children_list(self, block_id=None, start_cursor=None, page_size=100, **kw):
        ids = [i for i in self._parent_children(block_id) if not self.block_store[i]["in_trash"]]
        size = min(page_size or 100, self.list_page_size)
        start = int(start_cursor) if start_cursor else 0
        chunk = ids[start:start + size]
        more = start + size < len(ids)
        return {"object": "list", "results": [self._public(i) for i in chunk], "has_more": more,
                "next_cursor": str(start + size) if more else None}

    def _children_append(self, block_id=None, children=None, **kw):
        if len(children or []) > 100:
            raise api_error(400, APIErrorCode.ValidationError, message="children length should be ≤ 100")
        ids = [self._store_block(block_id, c) for c in children or []]
        return {"object": "list", "results": [self._public(i) for i in ids]}

    def _block_retrieve(self, block_id=None, **kw):
        if block_id not in self.block_store:
            raise not_found()
        b = self.block_store[block_id]
        parent = b["parent"]
        out = self._public(block_id)
        out["archived"] = out["in_trash"]
        out["parent"] = ({"type": "page_id", "page_id": parent} if parent in self.page_store
                         else {"type": "block_id", "block_id": parent})
        return out

    def _block_delete(self, block_id=None, **kw):
        if block_id not in self.block_store or self.block_store[block_id]["in_trash"]:
            raise not_found()
        self.block_store[block_id]["in_trash"] = True
        return self._public(block_id)
