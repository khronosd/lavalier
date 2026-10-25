"""The menu bar's words and its menu, as the window says them (web/src/pendant.ts, ported)."""

from datetime import datetime

import pytest

from lavalier import menubar
from lavalier.menubar import MenuItem, SEPARATOR, menu_model


def ms(h: int, m: int, s: int = 0) -> int:
    return int(datetime(2026, 10, 25, h, m, s).timestamp() * 1000)


def device(**over) -> dict:
    d = {"read_at_ms": 0, "has_all_fields": True, "recording_state": "LISTENING", "oldest_page": 1, "newest_page": 787,
         "soc": 94, "current_ma": -12, "usb_state": "USB_DISCONNECTED", "firmware_ver": "1.1.3", "storage_instance": 7,
         "pages_waiting": 787, "source": "sync", "charger_signal": "none", "age_s": 30}
    d.update(over)
    return d


def status(**over) -> dict:
    s = {"days_with_clips": [], "pending_transcripts": 0, "failed_clips": 0, "audio_bytes": 0, "capture_bytes": 0,
         "next_deletion": None, "last_import": None, "pinned": [], "long_presses": 0, "double_presses": 0,
         "last_process": None, "device": device(), "last_sync": None, "unmute_pending_since_ms": None,
         "muted_by_recorder_since_ms": None, "muted_by_owner_since_ms": None, "busy": False, "next_poll_ms": 0,
         "app": {"version": "1.0.0", "pid": 1, "started_ms": 0}}
    s.update(over)
    return s


def run(outcome: str, **over) -> dict:
    r = {"id": 1, "started_ms": ms(9, 31), "ended_ms": None, "outcome": outcome, "reason": "", "pages": 0,
         "messages": 0, "capture_id": None, "muted_by": None, "unmute": "n/a", "error": None}
    r.update(over)
    return r


def test_the_lamp_follows_only_the_latest_full_read():
    assert menubar.lamp_state(None) == "unknown"
    assert menubar.lamp_state(status(device=None)) == "unknown"
    assert menubar.lamp_state(status()) == "listening"
    assert menubar.lamp_state(status(device=device(recording_state="RECORDING"))) == "recording"
    assert menubar.lamp_state(status(device=device(recording_state="NOT_RECORDING"))) == "muted"
    # a partial read decodes as NOT_RECORDING and proves nothing
    assert menubar.lamp_state(status(device=device(has_all_fields=False, recording_state="NOT_RECORDING"))) == "unknown"
    assert menubar.lamp_state(status(device=device(recording_state="SOMETHING_NEW"))) == "unknown"
    assert [menubar.state_text(s) for s in ("listening", "recording", "muted", "unknown")] == \
        ["Listening", "Recording", "Muted", "No reading yet"]
    assert [menubar.SYMBOLS[s] for s in ("listening", "recording", "muted", "unknown")] == \
        ["waveform", "record.circle", "mic.slash", "circle.dotted"]


def test_the_words_match_the_windows():
    assert [menubar.age(s) for s in (5, 59, 60, 125, 3599, 3600, 7322)] == \
        ["just now", "just now", "as of 1 min ago", "as of 2 min ago", "as of 59 min ago", "as of 1 h ago", "as of 2 h ago"]
    assert menubar.battery_line(device(charger_signal="current")) == "Battery 94%, charging"
    assert menubar.battery_line(device(charger_signal="usb-cdc")) == "Battery 94%, on the charger"
    assert menubar.battery_line(device(charger_signal="quiet-polls")) == "Battery 94%, near the Mac"
    assert menubar.battery_line(device(charger_signal="none")) == "Battery 94%"
    assert menubar.pages_sentence(787) == "787 pages waiting, about 20 minutes of speech"
    assert menubar.pages_sentence(1) == "1 page waiting"
    assert menubar.pages_sentence(10) == "10 pages waiting"
    assert menubar.pages_sentence(40) == "40 pages waiting, about 1 minute of speech"
    assert menubar.pages_sentence(0) == ""
    assert menubar.pending_unmute_line(status()) == ""
    assert menubar.pending_unmute_line(status(unmute_pending_since_ms=ms(9, 5))) == \
        "Unmute pending since 09:05, hold the button or press Unmute"
    assert menubar.is_no_address("set pendant_address in config.toml")
    assert not menubar.is_no_address(None) and not menubar.is_no_address("Pendant not in range")


def test_what_a_sync_did_and_the_last_sync():
    line = lambda **o: menubar.sync_result_line({"sync": {**run("drained"), **o}, "process": None})
    assert line(outcome="drained", pages=3) == "Drained 3 pages"
    assert line(outcome="drained", pages=1) == "Drained 1 page"
    assert line(outcome="drained", pages=0) == "Nothing to drain"
    assert line(outcome="skipped") == "Nothing to drain"
    assert line(outcome="not-in-range") == "Pendant not in range"
    assert line(outcome="locked") == "Another process is using the pendant"
    assert line(outcome="error", error="set pendant_address in config.toml") == "set pendant_address in config.toml"
    assert line(outcome="refused", reason="firmware 1.1.20") == "firmware 1.1.20"
    assert line(outcome="odd") == "Sync ended: odd"
    assert menubar.sync_run_line(None) == "No sync yet"
    assert menubar.sync_run_line(run("drained", pages=212)) == "Drained 212 pages at 09:31"
    assert menubar.sync_run_line(run("not-in-range")) == "Pendant not in range at 09:31"


def test_what_a_mute_or_unmute_did_and_what_a_refusal_says():
    assert menubar.toggle_result_line({"ok": True, "state": "NOT_RECORDING", "error": None}) == "Muted"
    assert menubar.toggle_result_line({"ok": True, "state": "LISTENING", "error": None}) == "Listening"
    assert menubar.toggle_result_line({"ok": True, "state": "WEIRD", "error": None}) == "WEIRD"
    assert menubar.toggle_result_line({"ok": True, "state": None, "error": None}) == "Done"
    assert menubar.toggle_result_line({"ok": False, "state": "LISTENING", "error": None}) == "Not confirmed: LISTENING"
    assert menubar.toggle_result_line({"ok": False, "state": None, "error": "Pendant not in range"}) == "Pendant not in range"
    assert menubar.request_error_line(409, "busy") == "The pendant is busy, try again in a moment"
    assert menubar.request_error_line(503, "stopping") == "The app is stopping"
    assert menubar.request_error_line(504, "slow") == "The pendant took too long to answer"
    assert menubar.request_error_line(500, "boom") == "boom"
    assert menubar.request_error_line(None, "Connection refused") == "Connection refused"


def titles(items: list[MenuItem]) -> list[str]:
    return [i.title for i in items]


def test_the_menu_while_listening():
    symbol, items = menu_model(status(device=device(charger_signal="current", age_s=125), last_sync=run("drained", pages=212)))
    assert symbol == "waveform"
    assert titles(items) == [
        "Listening as of 2 min ago", "Battery 94%, charging", "787 pages waiting, about 20 minutes of speech",
        "Last sync: Drained 212 pages at 09:31", "-", "Sync now", "Mute", "-", "Open Lavalier",
    ]
    facts = items[:4]
    assert all(i.action is None for i in facts)
    assert [(i.title, i.action, i.enabled) for i in items if i.action] == \
        [("Sync now", "sync", True), ("Mute", "mute", True), ("Open Lavalier", "open", True)]
    assert items[4] is SEPARATOR


def test_the_menu_while_muted_offers_unmute_and_shows_a_pending_unmute():
    symbol, items = menu_model(status(device=device(recording_state="NOT_RECORDING", pages_waiting=0),
                                      unmute_pending_since_ms=ms(9, 5)))
    assert symbol == "mic.slash"
    assert titles(items) == [
        "Muted just now", "Battery 94%", "Last sync: No sync yet",
        "Unmute pending since 09:05, hold the button or press Unmute", "-", "Sync now", "Unmute", "-", "Open Lavalier",
    ]


def test_the_menu_with_no_reading_yet_and_before_the_first_status():
    symbol, items = menu_model(status(device=None))
    assert symbol == "circle.dotted"
    assert titles(items) == ["No reading yet", "Last sync: No sync yet", "-", "Sync now", "-", "Open Lavalier"]
    assert [i.enabled for i in items if i.action == "sync"] == [True]
    symbol, items = menu_model(None)
    assert symbol == "circle.dotted"
    assert titles(items) == ["No reading yet", "-", "Sync now", "-", "Open Lavalier"]
    assert [i.enabled for i in items if i.action == "sync"] == [False]  # nothing known yet


def test_the_menu_when_the_app_cannot_be_reached_keeps_the_last_reading_and_says_so():
    symbol, items = menu_model(status(), unreachable=True)
    assert symbol == "waveform"
    assert titles(items)[:2] == ["Listening just now", "Cannot reach the app"]


def test_the_menu_without_an_address_has_only_the_sentence_and_the_window():
    symbol, items = menu_model(status(device=None), no_address=True)
    assert symbol == "circle.dotted"
    assert titles(items) == ["Not set", "No pendant address set. Add it in Settings › Pendant.", "-", "Open Lavalier"]


def test_the_menu_while_an_action_runs_or_the_app_is_busy_disables_the_actions():
    _, items = menu_model(status(), busy_with="sync")
    assert titles(items)[0] == "Syncing…"
    assert [(i.action, i.enabled) for i in items if i.action] == [("sync", False), ("mute", False), ("open", True)]
    _, items = menu_model(status(device=device(recording_state="NOT_RECORDING")), busy_with="unmute")
    assert titles(items)[0] == "Unmuting…"
    _, items = menu_model(status(busy=True))
    assert titles(items)[0] == "Listening just now"
    assert [(i.action, i.enabled) for i in items if i.action] == [("sync", False), ("mute", False), ("open", True)]


def test_the_last_result_shows_under_the_facts_and_quit_only_when_started_by_hand():
    _, items = menu_model(status(), result="Drained 3 pages")
    assert "Drained 3 pages" in titles(items)
    assert titles(items).index("Drained 3 pages") < titles(items).index("-")
    _, items = menu_model(status(), standalone=True)
    assert titles(items)[-2:] == ["Open Lavalier", "Quit"]
    assert items[-1].action == "quit"


@pytest.mark.parametrize("lamp", ["listening", "recording", "muted", "unknown"])
def test_every_lamp_has_a_symbol_and_a_word(lamp):
    assert menubar.SYMBOLS[lamp] and menubar.state_text(lamp)
