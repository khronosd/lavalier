"""The CLI's side of the control server: is the app running, and call it."""

import http.client
import json
import time
from pathlib import Path
from typing import Optional

from lavalier.lock import _pid_alive

HEALTH_TIMEOUT_S = 1.0


class AppUnavailable(Exception):
    """The app could not be reached, or answered with something other than a result."""


class AppBusy(Exception):
    """The app is already running a device action, or that job (HTTP 409)."""


class AppRefused(AppUnavailable):
    """The app said no with a reason to show as it is (HTTP 400): no model chosen, no key, a bad day."""


def _token(token_path: Path) -> Optional[dict]:
    try:
        info = json.loads(Path(token_path).read_text(encoding="utf-8"))
        int(info["port"]), str(info["token"]), int(info["pid"])
        return info
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _request(info: dict, method: str, route: str, timeout_s: float,
             body: Optional[dict] = None) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", int(info["port"]), timeout=timeout_s)
    headers = {"Authorization": f"Bearer {info['token']}"}
    data = None if method == "GET" else b""
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, route, body=data, headers=headers)
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


def call(token_path: Path, method: str, route: str, *, body: Optional[dict] = None,
         timeout_s: float = 930) -> dict:
    info = _token(token_path)
    if info is None:
        raise AppUnavailable(f"no usable token file at {token_path}")
    try:
        status, body = _request(info, method, route, timeout_s, body)
    except (OSError, http.client.HTTPException) as e:
        raise AppUnavailable(str(e)) from e
    if status == 409:
        raise AppBusy()
    if status == 504:
        raise AppUnavailable("still running after 15 minutes; it continues in the app, see 'lavalier status'")
    if status == 204:
        return {}
    try:
        data = json.loads(body)
    except ValueError as e:
        raise AppUnavailable(f"HTTP {status}: unreadable reply") from e
    error = data.get("error") if isinstance(data, dict) else data
    if status == 400:
        raise AppRefused(str(error))
    if not 200 <= status < 300:
        raise AppUnavailable(f"HTTP {status}: {error}")
    return data


POLL_CAP_S = 1800  # a job still running after 30 minutes is given up on (it may still finish in the app)


def poll_job(token_path: Path, job_id: str, *, every_s: float = 1.0, sleep=time.sleep,
             clock=time.monotonic, cap_s: float = POLL_CAP_S) -> dict:
    """GET the job every `every_s` seconds until it is no longer running; returns the job."""
    deadline = clock() + cap_s
    while True:
        try:
            job = call(token_path, "GET", f"/api/jobs/{job_id}", timeout_s=30)
        except AppUnavailable as e:
            if "HTTP 404" in str(e):
                raise AppUnavailable("the app no longer knows this job (did it restart?)") from e
            raise
        if job["state"] != "running":
            return job
        if clock() >= deadline:
            raise AppUnavailable(f"no answer after {cap_s / 60:g} minutes; the job may still finish in the app")
        sleep(every_s)
