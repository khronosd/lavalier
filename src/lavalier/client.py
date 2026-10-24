"""The CLI's side of the control server: is the app running, and call it."""

import http.client
import json
from pathlib import Path
from typing import Optional

from lavalier.lock import _pid_alive

HEALTH_TIMEOUT_S = 1.0


class AppUnavailable(Exception):
    """The app could not be reached, or answered with something other than a result."""


class AppBusy(Exception):
    """The app is already running a device action (HTTP 409)."""


def _token(token_path: Path) -> Optional[dict]:
    try:
        info = json.loads(Path(token_path).read_text(encoding="utf-8"))
        int(info["port"]), str(info["token"]), int(info["pid"])
        return info
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _request(info: dict, method: str, route: str, timeout_s: float) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", int(info["port"]), timeout=timeout_s)
    try:
        conn.request(method, route, body=b"" if method == "POST" else None,
                     headers={"Authorization": f"Bearer {info['token']}"})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def app_running(token_path: Path) -> bool:
    """True only if the token file names a live pid whose server answers /api/health within 1 s."""
    info = _token(token_path)
    if info is None or not _pid_alive(int(info["pid"])):
        return False
    try:
        status, _ = _request(info, "GET", "/api/health", HEALTH_TIMEOUT_S)
    except (OSError, http.client.HTTPException):
        return False
    return status == 200


CALL_TIMEOUT_S = 930  # longer than the server's 900 s wait, so its 504 arrives first


def call(token_path: Path, method: str, route: str, *, timeout_s: float = 930) -> dict:
    info = _token(token_path)
    if info is None:
        raise AppUnavailable(f"no usable token file at {token_path}")
    try:
        status, body = _request(info, method, route, timeout_s)
    except (OSError, http.client.HTTPException) as e:
        raise AppUnavailable(str(e)) from e
    if status == 409:
        raise AppBusy()
    if status == 504:
        raise AppUnavailable("still running after 15 minutes; it continues in the app, see 'lavalier status'")
    try:
        data = json.loads(body)
    except ValueError as e:
        raise AppUnavailable(f"HTTP {status}: unreadable reply") from e
    if status != 200:
        raise AppUnavailable(f"HTTP {status}: {data.get('error') if isinstance(data, dict) else data}")
    return data
