"""The loopback control server: a token-protected HTTP front for the app process.

It knows nothing about the pendant. Every /api/ request is checked here (Origin, token, route)
and then handed to `app_like` on the app's event loop, so the server threads never touch the
database or the device themselves. The window's static files (`/`, `/assets/...`) need no
token: they carry no data.
"""

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import threading
from concurrent.futures import CancelledError as FutureCancelled
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from lavalier.playback import AudioExpired, UnknownClip
from lavalier.settings import SettingsError

ACTION_TIMEOUT_S = 900
DATA_TIMEOUT_S = 30
AUDIO_TIMEOUT_S = 120     # a first play waits for ffmpeg
MAX_BODY = 65536
ACTIONS = ("sync", "mute", "unmute", "status-live")
SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX = 50, 200

WEB_ROOT = Path(__file__).parent / "web" / "dist"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
    ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png", ".ico": "image/x-icon",
    ".json": "application/json", ".map": "application/json",
}

_log = logging.getLogger("lavalier.server")
_QUERY = re.compile(r"\?[^\s\"']*")


class _Busy(Exception):
    pass


class _BadRequest(Exception):
    pass


class AppStopping(Exception):
    """Raised by app_like.action() once the app is shutting down: the server answers 503."""


class NotFound(LookupError):
    """Raised by app_like for an id it does not know: the server answers 404."""


class ControlServer:
    def __init__(self, app_like, *, token_path: Path, port: int = 0,
                 loop: Optional[asyncio.AbstractEventLoop] = None, action_timeout_s: float = ACTION_TIMEOUT_S,
                 web_root: Path = WEB_ROOT):
        self.app_like = app_like
        self.web_root = Path(web_root)
        self.action_timeout_s = action_timeout_s
        self.token_path = Path(token_path)
        self.token = secrets.token_urlsafe(32)
        self._requested_port = port
        self._loop = loop
        self._own_loop: Optional[asyncio.AbstractEventLoop] = None
        self._threads: list[threading.Thread] = []
        self._httpd: Optional[ThreadingHTTPServer] = None
        self.port = 0

    @property
    def sock(self):
        return self._httpd.socket

    def start(self) -> int:
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:  # started outside any loop: run the app's coroutines on a private one
                self._own_loop = self._loop = asyncio.new_event_loop()
                self._spawn(self._own_loop.run_forever, "lavalier-server-loop")
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self._requested_port), _handler(self))
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._write_token_file()
        httpd = self._httpd
        self._spawn(lambda: httpd.serve_forever(poll_interval=0.05), "lavalier-server")
        _log.info("control server on 127.0.0.1:%d", self.port)
        return self.port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._own_loop is not None:
            self._own_loop.call_soon_threadsafe(self._own_loop.stop)
        for t in self._threads:
            t.join(10)
        self._threads.clear()
        if self._own_loop is not None:
            self._own_loop.close()
            self._own_loop = self._loop = None
        self._remove_token_file()

    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _write_token_file(self) -> None:
        data = json.dumps({"port": self.port, "token": self.token, "pid": os.getpid()})
        tmp = self.token_path.with_name(f"{self.token_path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data.encode())
        finally:
            os.close(fd)
        os.replace(tmp, self.token_path)

    def _remove_token_file(self) -> None:
        try:
            if json.loads(self.token_path.read_text()).get("token") != self.token:
                return  # another app process owns it now
        except (OSError, ValueError):
            return
        self.token_path.unlink(missing_ok=True)

    # called from the server threads

    def authorised(self, header: Optional[str]) -> bool:
        expected = f"Bearer {self.token}"
        return header is not None and hmac.compare_digest(header.encode(), expected.encode())

    def origin_ok(self, origin: Optional[str]) -> bool:
        return origin is None or origin == f"http://127.0.0.1:{self.port}"

    def on_loop(self, coro, timeout_s: float):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout_s)

    def snapshot(self) -> dict:
        async def snap():  # answers during shutdown too: the CLI's status reads it
            return self.app_like.snapshot()
        return self.on_loop(snap(), ACTION_TIMEOUT_S)

    def call(self, fn: Callable, *args, timeout_s: float = DATA_TIMEOUT_S):
        """Run a plain app method on the loop (the thread that owns the app's database) and wait;
        refused with AppStopping (503) once the app is shutting down."""
        async def run():
            if getattr(self.app_like, "stopping", False):
                raise AppStopping()
            return fn(*args)
        return self.on_loop(run(), timeout_s)

    async def unless_stopping(self, fn: Callable, *args):
        """Await an async app method on the loop, refused like `call` once the app is stopping."""
        if getattr(self.app_like, "stopping", False):
            raise AppStopping()
        return await fn(*args)

    def action(self, name: str) -> dict:
        async def run():
            # checked on the loop, where the device lock lives: nothing queues behind a running action
            if self.app_like.busy:
                raise _Busy()
            return await self.app_like.action(name)
        fut = asyncio.run_coroutine_threadsafe(run(), self._loop)
        try:
            return fut.result(self.action_timeout_s)
        except FutureTimeout:
            # only the HTTP wait gave up: the action keeps its device session (a drain cancelled
            # here would strand acked pages) and runs to the end; its result goes to the log
            _log.warning("%s still running after %ss; the reply is 504, the action continues", name,
                         self.action_timeout_s)
            fut.add_done_callback(lambda f: _log_late_result(name, f))
            raise


def _log_late_result(name: str, fut) -> None:
    if fut.cancelled():
        _log.info("%s (answered 504) was cancelled", name)
    elif fut.exception() is not None:
        _log.error("%s (answered 504) failed: %s", name, fut.exception())
    else:
        _log.info("%s (answered 504) finished: %s", name, fut.result())


# --- the routes: each handler takes (srv, request) and returns a _Response ---

@dataclass
class _Request:
    groups: tuple
    query: dict
    body: bytes


@dataclass
class _Response:
    status: int
    body: bytes
    content_type: str = "application/json"
    # never cached by default: the window's HTTP cache lives outside the state root and no sweep reaches it
    headers: dict = field(default_factory=lambda: {"Cache-Control": "no-store"})


def _json(body, status: int = 200) -> _Response:
    return _Response(status, json.dumps(body).encode())


def _health(srv, req):
    return _json({"ok": True, "pid": os.getpid()})


def _status(srv, req):
    return _json(srv.snapshot())


def _action(srv, req):
    return _json(srv.action(req.groups[0]))


def _days(srv, req):
    return _json(srv.call(srv.app_like.view_days))


def _parse_day(text: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise _BadRequest("bad date")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _BadRequest("bad date") from None


def _day(srv, req):
    return _json(srv.call(srv.app_like.view_day, _parse_day(req.groups[0])))


def _starred(srv, req):
    return _json(srv.call(srv.app_like.view_starred))


def _search(srv, req):
    text = req.query.get("q", [""])[0]
    raw = req.query.get("limit", [str(SEARCH_LIMIT_DEFAULT)])[0]
    if not re.fullmatch(r"\d{1,9}", raw) or int(raw) < 1:
        raise _BadRequest("limit must be a positive integer")
    return _json(srv.call(srv.app_like.view_search, text, min(int(raw), SEARCH_LIMIT_MAX)))


def _pin(srv, req):
    return _json(srv.call(srv.app_like.set_pinned, req.groups[0], True))


def _unpin(srv, req):
    return _json(srv.call(srv.app_like.set_pinned, req.groups[0], False))


def _get_settings(srv, req):
    return _json(srv.call(srv.app_like.get_settings))


def _put_settings(srv, req):
    try:
        patch = json.loads(req.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _BadRequest("the body must be a JSON object") from None
    if not isinstance(patch, dict):
        raise _BadRequest("the body must be a JSON object")
    return _json(srv.call(srv.app_like.update_settings, patch))


def _audio(srv, req):
    path = srv.on_loop(srv.unless_stopping(srv.app_like.audio_file, req.groups[0]), AUDIO_TIMEOUT_S)
    try:
        data = Path(path).read_bytes()   # read once the transcode is done; no database involved
    except FileNotFoundError:            # retention evicted it in between
        raise AudioExpired(req.groups[0]) from None
    return _Response(200, data, "audio/mp4")


def _file(path: Path, *, no_store: bool = False) -> _Response:
    ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return _Response(200, path.read_bytes(), ctype, {"Cache-Control": "no-store"} if no_store else {})


def _index(srv, req):
    index = srv.web_root / "index.html"
    if not index.is_file():
        return _json({"error": "not found"}, 404)
    return _file(index, no_store=True)


def _asset(srv, req):
    """Only a regular file inside web_root/assets, whatever the request spells: decoded, no '..',
    no absolute path, no backslash or NUL, and still inside once symlinks are resolved."""
    name = unquote(req.groups[0])
    parts = name.split("/")
    if (not name or name.startswith("/") or "\\" in name or "\x00" in name
            or any(p in ("", ".", "..") for p in parts)):
        return _json({"error": "not found"}, 404)
    assets = (srv.web_root / "assets").resolve()
    target = (assets / name).resolve()
    if not target.is_relative_to(assets) or not target.is_file():
        return _json({"error": "not found"}, 404)
    return _file(target)


# (method, pattern over the raw path, handler); /api/ routes need the token and a local Origin
_API_ROUTES = [
    ("GET", r"/api/health", _health),
    ("GET", r"/api/status", _status),
    ("POST", r"/api/(" + "|".join(re.escape(a) for a in ACTIONS) + r")", _action),
    ("GET", r"/api/days", _days),
    ("GET", r"/api/day/([^/]+)", _day),
    ("GET", r"/api/starred", _starred),
    ("GET", r"/api/search", _search),
    ("GET", r"/api/audio/(clip_[A-Za-z0-9_.-]+)\.m4a", _audio),
    ("POST", r"/api/pin/([^/]+)", _pin),
    ("POST", r"/api/unpin/([^/]+)", _unpin),
    ("GET", r"/api/settings", _get_settings),
    ("PUT", r"/api/settings", _put_settings),
]
_STATIC_ROUTES = [
    ("GET", r"/", _index),
    ("GET", r"/assets/(.+)", _asset),
]


def _compile(routes):
    return [(method, re.compile(pattern), handler) for method, pattern, handler in routes]


API_ROUTES = _compile(_API_ROUTES)
STATIC_ROUTES = _compile(_STATIC_ROUTES)


def _match(routes, method: str, path: str):
    for m, pattern, handler in routes:
        found = pattern.fullmatch(path)
        if m == method and found:
            return handler, found.groups()
    return None, ()


def _handler(srv: ControlServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "lavalier"
        sys_version = ""

        def log_message(self, format, *args):  # noqa: A002 - the stdlib's signature
            # paths only: a query string can carry the launch token (/?token=...), which no log may keep
            _log.debug("%s %s", self.address_string(), _QUERY.sub("", format % args))

        def _send(self, r: _Response) -> None:
            self.send_response(r.status)
            self.send_header("Content-Type", r.content_type)
            self.send_header("Content-Length", str(len(r.body)))
            for k, v in r.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(r.body)

        def _reply(self, status: int, body: dict) -> None:
            self._send(_json(body, status))

        def _read_body(self) -> Optional[bytes]:
            """The request body, or None when its length is unusable or over MAX_BODY (the reply is then 413)."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = MAX_BODY + 1
            if length > MAX_BODY or length < 0:
                self.close_connection = True  # the unread body must not be parsed as the next request
                return None
            return self.rfile.read(length) if length > 0 else b""

        def _route(self, method: str, body: bytes = b"") -> None:
            url = urlsplit(self.path)
            path = url.path
            if not (path == "/api" or path.startswith("/api/")):
                handler, groups = _match(STATIC_ROUTES, method, path)
                if handler is None:
                    return self._reply(404, {"error": "not found"})
                try:
                    return self._send(handler(srv, _Request(groups, {}, b"")))
                except Exception as e:
                    _log.exception("%s %s failed", method, path)
                    return self._reply(500, {"error": str(e)})
            if not srv.origin_ok(self.headers.get("Origin")):
                return self._reply(403, {"error": "forbidden origin"})
            if not srv.authorised(self.headers.get("Authorization")):
                return self._reply(401, {"error": "unauthorised"})
            handler, groups = _match(API_ROUTES, method, path)
            if handler is None:
                return self._reply(404, {"error": "not found"})
            try:
                return self._send(handler(srv, _Request(groups, parse_qs(url.query), body)))
            except _BadRequest as e:
                return self._reply(400, {"error": str(e)})
            except SettingsError as e:
                return self._reply(400, {"error": str(e), "field": e.field})
            except (NotFound, UnknownClip):
                return self._reply(404, {"error": "not found"})
            except AudioExpired:
                return self._reply(410, {"error": "audio expired"})
            except _Busy:
                return self._reply(409, {"error": "busy"})
            except (AppStopping, FutureCancelled):  # refused, or cancelled by the shutdown
                return self._reply(503, {"error": "stopping"})
            except FutureTimeout:
                return self._reply(504, {"error": "timeout"})
            except Exception as e:
                _log.exception("%s %s failed", method, path)
                return self._reply(500, {"error": str(e)})

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def _route_with_body(self, method: str) -> None:
            body = self._read_body()
            if body is None:
                return self._reply(413, {"error": "body too large"})
            self._route(method, body)

        def do_POST(self):  # noqa: N802
            self._route_with_body("POST")

        def do_PUT(self):  # noqa: N802
            self._route_with_body("PUT")

    return Handler
