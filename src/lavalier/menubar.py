"""`lavalier menubar`: the pendant in the macOS menu bar.

The pendant's words and the menu, as pure functions: the window says the same things (web/src/pendant.ts),
and this module keeps them in step. The menu bar is read-only on device state, like the window's pill: what
it says comes from the latest status read, never from what an action was meant to do. The process logic and
the AppKit glue come in later tasks; nothing here imports AppKit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

LAMPS = ("listening", "recording", "muted", "unknown")

STATE_TEXT = {"listening": "Listening", "recording": "Recording", "muted": "Muted", "unknown": "No reading yet"}

# SF Symbols for the status item, one per lamp state; drawn as template images so they follow the menu bar.
SYMBOLS = {"listening": "waveform", "recording": "record.circle", "muted": "mic.slash", "unknown": "circle.dotted"}

BUSY_WORDS = {"sync": "Syncing…", "mute": "Muting…", "unmute": "Unmuting…"}
CHARGER_WORDS = {"current": "charging", "usb-cdc": "on the charger", "quiet-polls": "near the Mac"}
TOGGLE_STATE = {"NOT_RECORDING": "Muted", "LISTENING": "Listening", "RECORDING": "Recording"}

NO_ADDRESS = "No pendant address set. Add it in Settings › Pendant."
NOT_SET = "Not set"
UNREACHABLE = "Cannot reach the app"
PENDANT_BUSY = "The pendant is busy, try again in a moment"
APP_STOPPING = "The app is stopping"
TOO_LONG = "The pendant took too long to answer"

SECONDS_PER_PAGE = 1.5


def lamp_state(status: Optional[dict]) -> str:
    """The lamp mirrors the pendant's LED, from the latest full read only."""
    d = (status or {}).get("device")
    if not d or not d.get("has_all_fields"):
        return "unknown"  # a partial read decodes as NOT_RECORDING and proves nothing
    return {"LISTENING": "listening", "RECORDING": "recording", "NOT_RECORDING": "muted"}.get(d.get("recording_state"), "unknown")


def state_text(lamp: str) -> str:
    return STATE_TEXT[lamp]


def age(seconds: float) -> str:
    """How old a reading is: "just now", "as of 2 min ago", "as of 2 h ago"."""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"as of {int(seconds // 60)} min ago"
    return f"as of {int(seconds // 3600)} h ago"


def hm(ms: int) -> str:
    """Local wall-clock time of an epoch ms, "09:05"."""
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M")


def battery_line(device: dict) -> str:
    """"Battery 94%, charging"; the charger words are left out when there is no signal."""
    words = CHARGER_WORDS.get(device.get("charger_signal", ""))
    return f"Battery {device['soc']}%, {words}" if words else f"Battery {device['soc']}%"


def pages_sentence(pages: int) -> str:
    """"787 pages waiting, about 20 minutes of speech"; "1 page waiting"; "" with none."""
    if pages <= 0:
        return ""
    head = "1 page waiting" if pages == 1 else f"{pages} pages waiting"
    minutes = round(pages * SECONDS_PER_PAGE / 60)
    if minutes < 1:
        return head
    return f"{head}, about {minutes} {'minute' if minutes == 1 else 'minutes'} of speech"


def _sync_words(outcome: str, pages: int, error: Optional[str], reason: Optional[str]) -> str:
    if outcome == "drained":
        if pages > 0:
            return f"Drained {pages} {'page' if pages == 1 else 'pages'}"
        return "Nothing to drain"
    if outcome == "skipped":
        return "Nothing to drain"
    if outcome == "not-in-range":
        return "Pendant not in range"
    if outcome == "locked":
        return "Another process is using the pendant"
    return error or reason or f"Sync ended: {outcome}"


def sync_result_line(result: dict) -> str:
    """What a sync (POST /api/sync) did, in one line."""
    s = result["sync"]
    return _sync_words(s.get("outcome", ""), int(s.get("pages") or 0), s.get("error"), s.get("reason"))


def sync_run_line(run: Optional[dict]) -> str:
    """The last sync and when: "Drained 212 pages at 09:31"; "No sync yet" with none."""
    if not run:
        return "No sync yet"
    words = _sync_words(run.get("outcome", ""), int(run.get("pages") or 0), run.get("error"), run.get("reason"))
    return f"{words} at {hm(int(run['started_ms']))}"


def toggle_result_line(result: dict) -> str:
    """What a mute or unmute (POST /api/mute, /api/unmute) did: the state read back, or the error."""
    if not result.get("ok"):
        return result.get("error") or f"Not confirmed: {result.get('state') or 'no reading'}"
    state = result.get("state")
    return TOGGLE_STATE.get(state or "", state or "Done")


def request_error_line(status_code: Optional[int], message: str) -> str:
    """A request the app refused or could not answer."""
    if status_code == 409:
        return PENDANT_BUSY
    if status_code == 503:
        return APP_STOPPING
    if status_code == 504:
        return TOO_LONG
    return message


def is_no_address(text: Optional[str]) -> bool:
    """The app's words when config.toml has no pendant_address."""
    return bool(text) and "set pendant_address" in text


def pending_unmute_line(status: Optional[dict]) -> str:
    """"Unmute pending since 09:05, hold the button or press Unmute", or "" with none pending."""
    since = (status or {}).get("unmute_pending_since_ms")
    if not since:
        return ""
    return f"Unmute pending since {hm(int(since))}, hold the button or press Unmute"


@dataclass(frozen=True)
class MenuItem:
    """A line of the menu: a fact (no action), an action, or the separator."""
    title: str
    action: Optional[str] = None
    enabled: bool = True


SEPARATOR = MenuItem("-")


def menu_model(status: Optional[dict], *, no_address: bool = False, unreachable: bool = False,
               busy_with: Optional[str] = None, result: Optional[str] = None,
               standalone: bool = False) -> tuple[str, list[MenuItem]]:
    """The status item's symbol and its menu, from the latest status read.

    The facts first (the state with the reading's age, the battery, the pages waiting, the last sync, an
    unmute still pending, the last action's result), then Sync now and Mute or Unmute (disabled while the app
    is busy, an action runs, or nothing is known yet), then Open Lavalier and, started by hand, Quit. Without
    an address the facts give way to the window's sentence about Settings › Pendant.
    """
    lamp = "unknown" if no_address else lamp_state(status)
    items: list[MenuItem] = []
    if no_address:
        items += [MenuItem(NOT_SET), MenuItem(NO_ADDRESS)]
    else:
        device = (status or {}).get("device") if lamp != "unknown" else None
        word = BUSY_WORDS[busy_with] if busy_with else state_text(lamp)
        items.append(MenuItem(f"{word} {age(device['age_s'])}" if device and not busy_with else word))
        if unreachable:
            items.append(MenuItem(UNREACHABLE))
        if device:
            items.append(MenuItem(battery_line(device)))
            pages = pages_sentence(int(device.get("pages_waiting") or 0))
            if pages:
                items.append(MenuItem(pages))
        if status is not None:
            items.append(MenuItem(f"Last sync: {sync_run_line(status.get('last_sync'))}"))
        pending = pending_unmute_line(status)
        if pending:
            items.append(MenuItem(pending))
        if result:
            items.append(MenuItem(result))
        items.append(SEPARATOR)
        disabled = status is None or bool(status.get("busy")) or busy_with is not None
        items.append(MenuItem("Sync now", "sync", enabled=not disabled))
        if lamp == "muted":
            items.append(MenuItem("Unmute", "unmute", enabled=not disabled))
        elif lamp in ("listening", "recording"):
            items.append(MenuItem("Mute", "mute", enabled=not disabled))
    items.append(SEPARATOR)
    items.append(MenuItem("Open Lavalier", "open"))
    if standalone:
        items.append(MenuItem("Quit", "quit"))
    return SYMBOLS[lamp], items


# --- the process ---

import http.client  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
from typing import Callable, Protocol  # noqa: E402

from lavalier import agent, client  # noqa: E402
from lavalier.config import Config  # noqa: E402

POLL_EVERY_S = 15.0
STATUS_TIMEOUT_S = 5.0
WINDOW_ARGS = ["-m", "lavalier.cli", "window"]


def api(token_path, method: str, route: str, timeout_s: float) -> tuple[int, dict]:
    """One request to the app: the HTTP status and the JSON body ({} when there is none). Raises
    client.AppUnavailable when the app cannot be reached at all."""
    info = client._token(token_path)
    if info is None:
        raise client.AppUnavailable(f"no usable token file at {token_path}")
    try:
        status, body = client._request(info, method, route, timeout_s)
    except (OSError, http.client.HTTPException) as e:
        raise client.AppUnavailable(str(e)) from e
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        data = {}
    return status, data if isinstance(data, dict) else {}


def window_program(cfg: Config, **kw) -> list[str]:
    """How to start the window: the program the agent would run, told to run the CLI's window command."""
    program = agent.default_program(cfg, **kw)
    if program[-2:] == ["-m", "lavalier.app"]:
        return program[:-2] + WINDOW_ARGS
    return program + WINDOW_ARGS


def spawn_window(cfg: Config) -> None:
    subprocess.Popen(window_program(cfg), start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Bar(Protocol):
    """What the status item needs from AppKit (menubar_cocoa) or a fake (tests)."""

    def set_icon(self, symbol: str, description: str) -> None: ...
    def set_menu(self, items: list[MenuItem], on_action: Callable[[str], None]) -> None: ...
    def every(self, seconds: float, fn: Callable[[], None]) -> None: ...
    def call_soon(self, fn: Callable[[], None]) -> None: ...
    def run(self) -> None: ...
    def stop(self) -> None: ...


class MenuBar:
    """The status item's life: a status read every 15 s, the menu redrawn from it, actions run on a worker
    thread through the app's API, the window opened as a process, and the end when the parent app is gone.
    No live reads from here: the window does those when it is in front."""

    def __init__(self, bar: Bar, token_path, *, parent_pid: Optional[int] = None, api=api, thread=threading.Thread,
                 parent_alive=client._pid_alive, spawn_window: Callable[[], None] = lambda: None):
        self.bar = bar
        self.token_path = token_path
        self.parent_pid = parent_pid
        self.api = api
        self.thread = thread
        self.parent_alive = parent_alive
        self.spawn_window = spawn_window
        self.status: Optional[dict] = None
        self.no_address = False
        self.unreachable = False
        self.busy_with: Optional[str] = None
        self.result: Optional[str] = None
        self.stopped = False

    def start(self) -> None:
        self.tick()
        if self.stopped:  # the parent was gone before the first tick: nothing to run
            return
        self.bar.every(POLL_EVERY_S, self.tick)
        self.bar.run()

    def tick(self) -> None:
        if self.parent_pid is not None and not self.parent_alive(self.parent_pid):
            self.stopped = True
            self.bar.stop()
            return
        self.read_status()
        self.redraw()

    def read_status(self) -> None:
        try:
            code, data = self.api(self.token_path, "GET", "/api/status", STATUS_TIMEOUT_S)
        except client.AppUnavailable:
            self.unreachable = True  # the last reading stays on show
            return
        if code != 200:
            self.unreachable = True
            return
        self.status = data
        self.unreachable = False
        if is_no_address((data.get("last_sync") or {}).get("error")):
            self.no_address = True

    def redraw(self) -> None:
        symbol, items = menu_model(self.status, no_address=self.no_address, unreachable=self.unreachable,
                                   busy_with=self.busy_with, result=self.result, standalone=self.parent_pid is None)
        self.bar.set_icon(symbol, f"Pendant: {items[0].title}")
        self.bar.set_menu(items, self.on_action)

    def on_action(self, name: str) -> None:
        if name == "open":
            self.spawn_window()
        elif name == "quit":
            self.bar.stop()
        elif name in BUSY_WORDS and self.busy_with is None:
            self.busy_with = name
            self.result = None
            self.redraw()
            self.thread(target=self._run_action, args=(name,), daemon=True).start()

    def _run_action(self, name: str) -> None:
        """On the worker thread: the request, then its line; the redraw hops back to the main thread."""
        route = "/api/sync" if name == "sync" else f"/api/{name}"
        try:
            code, data = self.api(self.token_path, "POST", route, client.CALL_TIMEOUT_S)
            if code != 200:
                line = request_error_line(code, str(data.get("error") or f"HTTP {code}"))
            elif name == "sync":
                line = sync_result_line(data)
                sync = data.get("sync") or {}
                self.no_address = is_no_address(sync.get("error")) or is_no_address(sync.get("reason"))
            else:
                line = toggle_result_line(data)
                self.no_address = is_no_address(data.get("error"))
        except client.AppUnavailable as e:
            line = request_error_line(None, str(e))
            if is_no_address(str(e)):
                self.no_address = True

        def finish() -> None:
            self.busy_with = None
            self.result = line
            self.read_status()  # the app's view again: an action is a reason to look
            self.redraw()

        self.bar.call_soon(finish)


def main(*, token_path, cfg: Config, parent_pid: Optional[int] = None, bar: Optional[Bar] = None) -> int:
    """Run the status item until the parent app is gone (or Quit, when started by hand)."""
    if bar is None:
        from lavalier.menubar_cocoa import CocoaBar
        bar = CocoaBar()
    MenuBar(bar, token_path, parent_pid=parent_pid, spawn_window=lambda: spawn_window(cfg)).start()
    return 0
