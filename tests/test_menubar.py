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


# --- the process: a fake bar, a fake API, threads that run at once ---

import sys
from pathlib import Path
from types import SimpleNamespace

from lavalier import client
from lavalier.config import Config
from lavalier.menubar import POLL_EVERY_S, MenuBar, api, window_program


class FakeBar:
    def __init__(self):
        self.icons: list[tuple[str, str]] = []
        self.menus: list[list[MenuItem]] = []
        self.timers: list[tuple[float, object]] = []
        self.running = False
        self.on_action = None

    def set_icon(self, symbol, description):
        self.icons.append((symbol, description))

    def set_menu(self, items, on_action):
        self.menus.append(list(items))
        self.on_action = on_action

    def every(self, seconds, fn):
        self.timers.append((seconds, fn))

    def call_soon(self, fn):
        fn()

    def run(self):
        self.running = True

    def stop(self):
        self.running = False

    def press(self, action):
        self.on_action(action)

    def titles(self, n=-1):
        return [i.title for i in self.menus[n]]

    def enabled(self, action, n=-1):
        return [i.enabled for i in self.menus[n] if i.action == action][0]


class FakeApi:
    """Answers GET /api/status with `status_reply` and anything else from `replies` (a (code, data) or an
    exception to raise)."""

    def __init__(self):
        self.status_reply = (200, status())
        self.replies: dict = {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, token_path, method, route, timeout_s):
        self.calls.append((method, route))
        reply = self.status_reply if (method, route) == ("GET", "/api/status") else self.replies[route]
        if isinstance(reply, Exception):
            raise reply
        return reply


def run_now(target, args=(), daemon=True):
    return SimpleNamespace(start=lambda: target(*args))


def make(parent_pid=4242, alive=lambda pid: True, spawn=lambda: None):
    """A menu bar as the app spawns it (a live parent), unless a test says otherwise."""
    bar, fake = FakeBar(), FakeApi()
    mb = MenuBar(bar, Path("/nowhere/.server.json"), api=fake, thread=run_now, parent_pid=parent_pid,
                 parent_alive=alive, spawn_window=spawn)
    return bar, fake, mb


def test_start_draws_the_icon_and_the_menu_from_the_first_read_and_polls_every_15_s():
    bar, fake, mb = make()
    mb.start()
    assert bar.running
    assert fake.calls == [("GET", "/api/status")]
    assert bar.icons[-1] == ("waveform", "Pendant: Listening just now")
    assert bar.titles() == ["Listening just now", "Battery 94%", "787 pages waiting, about 20 minutes of speech",
                            "Last sync: No sync yet", "-", "Sync now", "Mute", "-", "Open Lavalier"]
    assert bar.timers == [(POLL_EVERY_S, mb.tick)]


def test_an_unreachable_app_is_said_so_and_the_last_reading_kept():
    bar, fake, mb = make()
    fake.status_reply = client.AppUnavailable("Connection refused")
    mb.start()
    assert bar.icons[-1][0] == "circle.dotted"
    assert bar.titles()[:2] == ["No reading yet", "Cannot reach the app"]
    assert bar.enabled("sync") is False
    fake.status_reply = (200, status())
    mb.tick()
    assert bar.titles()[0] == "Listening just now" and "Cannot reach the app" not in bar.titles()
    fake.status_reply = client.AppUnavailable("Connection refused")
    mb.tick()
    assert bar.titles()[:2] == ["Listening just now", "Cannot reach the app"]  # the last reading stays


def test_no_address_in_the_last_sync_gives_the_settings_sentence():
    bar, fake, mb = make()
    fake.status_reply = (200, status(device=None, last_sync=run("error", error="set pendant_address in config.toml")))
    mb.start()
    assert bar.icons[-1] == ("circle.dotted", "Pendant: Not set")
    assert bar.titles() == ["Not set", "No pendant address set. Add it in Settings › Pendant.", "-", "Open Lavalier"]


def test_sync_now_shows_syncing_then_the_result_and_reads_again():
    bar, fake, mb = make()
    fake.replies["/api/sync"] = (200, {"sync": {**run("drained"), "pages": 3}, "process": None})
    mb.start()
    bar.press("sync")
    # while it ran: the word, and the actions disabled
    assert bar.titles(-2)[0] == "Syncing…"
    assert bar.enabled("sync", -2) is False and bar.enabled("mute", -2) is False
    # then: the result under the facts, a fresh read, the actions back
    assert fake.calls[-2:] == [("POST", "/api/sync"), ("GET", "/api/status")]
    assert "Drained 3 pages" in bar.titles() and bar.titles()[0] == "Listening just now"
    assert bar.enabled("sync") is True and bar.enabled("mute") is True


def test_a_busy_app_and_an_app_that_cannot_be_reached_say_so_as_the_result():
    bar, fake, mb = make()
    fake.replies["/api/mute"] = (409, {"error": "busy"})
    mb.start()
    bar.press("mute")
    assert "The pendant is busy, try again in a moment" in bar.titles()
    fake.replies["/api/mute"] = client.AppUnavailable("Connection refused")
    bar.press("mute")
    assert "Connection refused" in bar.titles()
    fake.replies["/api/mute"] = (503, {"error": "stopping"})
    bar.press("mute")
    assert "The app is stopping" in bar.titles()


def test_mute_and_unmute_report_the_state_read_back():
    bar, fake, mb = make()
    fake.replies["/api/mute"] = (200, {"ok": True, "state": "NOT_RECORDING", "error": None})
    mb.start()
    bar.press("mute")
    assert fake.calls[-2] == ("POST", "/api/mute") and "Muted" in bar.titles()
    fake.status_reply = (200, status(device=device(recording_state="NOT_RECORDING")))
    fake.replies["/api/unmute"] = (200, {"ok": False, "state": None, "error": "set pendant_address in config.toml"})
    mb.tick()
    assert bar.enabled("unmute") is True
    bar.press("unmute")
    assert bar.titles()[:2] == ["Not set", "No pendant address set. Add it in Settings › Pendant."]


def test_a_second_press_while_one_runs_is_ignored():
    bar, fake, mb = make()
    fake.replies["/api/sync"] = (200, {"sync": run("skipped"), "process": None})
    mb.start()
    mb.busy_with = "sync"
    bar.press("sync")
    assert ("POST", "/api/sync") not in fake.calls


def test_the_child_stops_when_its_parent_is_gone_but_a_standalone_one_stays():
    bar, fake, mb = make(parent_pid=4242, alive=lambda pid: False)
    mb.start()
    assert not bar.running
    bar, fake, mb = make(parent_pid=None, alive=lambda pid: False)
    mb.start()
    mb.tick()
    assert bar.running and bar.titles()[-1] == "Quit"
    bar.press("quit")
    assert not bar.running


def test_open_lavalier_spawns_the_window():
    opened = []
    bar, fake, mb = make(spawn=lambda: opened.append(True))
    mb.start()
    bar.press("open")
    assert opened == [True]


def test_window_program_follows_the_agents_choice_of_program(tmp_path):
    assert window_program(Config(), bundle_default=tmp_path / "none") == [sys.executable, "-m", "lavalier.cli", "window"]
    bundle = tmp_path / "Lavalier.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    assert window_program(Config(), bundle_default=bundle) == [str(bundle / "Contents" / "MacOS" / "Lavalier"), "-m", "lavalier.cli", "window"]


def test_api_returns_the_code_and_the_json_and_raises_when_the_app_is_away(monkeypatch, tmp_path):
    token = tmp_path / ".server.json"
    token.write_text('{"port": 1, "token": "t", "pid": 1}')
    monkeypatch.setattr(client, "_request", lambda info, method, route, timeout_s, body=None: (200, b'{"a": 1}'))
    assert api(token, "GET", "/api/status", 5.0) == (200, {"a": 1})
    monkeypatch.setattr(client, "_request", lambda *a, **k: (502, b"not json"))
    assert api(token, "GET", "/api/status", 5.0) == (502, {})
    def refuse(*a, **k):
        raise OSError("Connection refused")
    monkeypatch.setattr(client, "_request", refuse)
    with pytest.raises(client.AppUnavailable):
        api(token, "GET", "/api/status", 5.0)
    with pytest.raises(client.AppUnavailable):
        api(tmp_path / "missing.json", "GET", "/api/status", 5.0)



# --- the app's side ---

import subprocess

from lavalier.menubar import RESPAWN_AFTER_S, MenuBarChild, menubar_program


class FakeProc:
    def __init__(self, argv, hang=False, **kw):
        self.argv, self.kw, self.hang = argv, kw, hang
        self.returncode = None
        self.terminated = self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.hang:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.returncode


def child(cfg=None, hang=False, log_path=None):
    procs: list[FakeProc] = []
    clock = {"t": 1000.0}

    def popen(argv, **kw):
        procs.append(FakeProc(argv, hang=hang, **kw))
        return procs[-1]

    c = MenuBarChild(cfg or Config(), log_path=log_path, popen=popen, now=lambda: clock["t"], pid=lambda: 77,
                     program=lambda cfg, pid: ["prog", "--parent", str(pid)])
    return c, procs, clock


def test_menubar_program_is_the_agents_program_told_to_run_the_menubar_for_this_parent(tmp_path):
    assert menubar_program(Config(), 77, bundle_default=tmp_path / "none") == \
        [sys.executable, "-m", "lavalier.cli", "menubar", "--parent", "77"]
    bundle = tmp_path / "Lavalier.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    assert menubar_program(Config(), 77, bundle_default=bundle)[:2] == [str(bundle / "Contents" / "MacOS" / "Lavalier"), "-m"]


def test_the_app_starts_the_status_item_for_its_own_pid_with_its_output_in_a_log(tmp_path):
    c, procs, _ = child(log_path=tmp_path / "logs" / "menubar.log")
    c.start()
    assert [p.argv for p in procs] == [["prog", "--parent", "77"]]
    assert procs[0].kw["stdin"] is subprocess.DEVNULL and procs[0].kw["start_new_session"] is True
    assert Path(procs[0].kw["stdout"].name) == tmp_path / "logs" / "menubar.log"
    procs[0].kw["stdout"].close()


def test_a_child_that_died_is_started_again_only_after_the_cooldown():
    c, procs, clock = child()
    c.start()
    c.check()
    assert len(procs) == 1  # alive: nothing to do
    procs[0].returncode = 1
    clock["t"] += RESPAWN_AFTER_S - 1
    c.check()
    assert len(procs) == 1
    clock["t"] += 1
    c.check()
    assert len(procs) == 2


def test_stop_ends_the_child_and_kills_one_that_will_not_end():
    c, procs, _ = child()
    c.start()
    c.stop()
    assert procs[0].terminated and not procs[0].killed and c.proc is None
    c.stop()  # nothing to do twice
    c, procs, _ = child(hang=True)
    c.start()
    c.stop()
    assert procs[0].terminated and procs[0].killed


def test_menu_bar_off_spawns_nothing():
    c, procs, _ = child(cfg=Config(menu_bar=False))
    c.start()
    c.check()
    c.stop()
    assert procs == []
