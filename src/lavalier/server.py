"""The loopback control server: a token-protected HTTP front for the app process.

It knows nothing about the pendant. Every request is checked here (token, Origin, route) and
then handed to `app_like` on the app's event loop, so the server threads never touch the
database or the device themselves.
"""

import asyncio
import hmac
import json
import logging
import os
import secrets
import threading
from concurrent.futures import CancelledError as FutureCancelled
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

ACTION_TIMEOUT_S = 900
ACTIONS = ("sync", "mute", "unmute", "status-live")

_log = logging.getLogger("lavalier.server")


class _Busy(Exception):
    pass


class AppStopping(Exception):
    """Raised by app_like.action() once the app is shutting down: the server answers 503."""


class ControlServer:
    def __init__(self, app_like, *, token_path: Path, port: int = 0,
                 loop: Optional[asyncio.AbstractEventLoop] = None, action_timeout_s: float = ACTION_TIMEOUT_S):
        self.app_like = app_like
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
        async def snap():
            return self.app_like.snapshot()
        return self.on_loop(snap(), ACTION_TIMEOUT_S)

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


def _handler(srv: ControlServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "lavalier"
        sys_version = ""

        def log_message(self, format, *args):  # noqa: A002 - the stdlib's signature
            _log.debug("%s %s", self.address_string(), format % args)

        def _reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self, method: str) -> None:
            if not srv.origin_ok(self.headers.get("Origin")):
                return self._reply(403, {"error": "forbidden origin"})
            if not srv.authorised(self.headers.get("Authorization")):
                return self._reply(401, {"error": "unauthorised"})
            path = self.path.split("?", 1)[0]
            try:
                if method == "GET" and path == "/api/health":
                    return self._reply(200, {"ok": True, "pid": os.getpid()})
                if method == "GET" and path == "/api/status":
                    return self._reply(200, srv.snapshot())
                if method == "POST" and path.startswith("/api/") and path[5:] in ACTIONS:
                    return self._reply(200, srv.action(path[5:]))
            except _Busy:
                return self._reply(409, {"error": "busy"})
            except (AppStopping, FutureCancelled):  # refused, or cancelled by the shutdown
                return self._reply(503, {"error": "stopping"})
            except FutureTimeout:
                return self._reply(504, {"error": "timeout"})
            except Exception as e:
                _log.exception("%s %s failed", method, path)
                return self._reply(500, {"error": str(e)})
            return self._reply(404, {"error": "not found"})

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(min(length, 65536))
            self._route("POST")

    return Handler
