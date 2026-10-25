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
