import json
import shutil

import pytest

from conftest import CLIP, CONV, get, post, put

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")


def test_health_needs_token_and_status_returns_snapshot(server):
    assert get(server, "/api/health", token=None).status == 401
    assert get(server, "/api/health", token="wrong").status == 401
    assert json.loads(get(server, "/api/status").read()) == {"x": 1}


def test_foreign_origin_is_rejected(server):
    assert get(server, "/api/status", origin="http://evil.test").status == 403
    assert get(server, "/api/status", origin=f"http://127.0.0.1:{server.port}").status == 200


def test_actions_run_on_the_app_and_busy_is_409(server, fake_app):
    assert json.loads(post(server, "/api/mute").read()) == {"did": "mute"}
    fake_app.busy = True
    assert post(server, "/api/sync").status == 409


def test_token_file_is_private_and_removed_on_stop(server, token_path):
    assert oct(token_path.stat().st_mode & 0o777) == "0o600" and json.loads(token_path.read_text())["port"] == server.port
    server.stop(); assert not token_path.exists()


def test_server_binds_loopback_only(server):
    assert server.sock.getsockname()[0] == "127.0.0.1"


def test_health_reports_the_pid_and_the_token_file_names_it(server, token_path):
    import os
    body = json.loads(get(server, "/api/health").read())
    assert body == {"ok": True, "pid": os.getpid()}
    assert json.loads(token_path.read_text()) == {"port": server.port, "token": server.token, "pid": os.getpid()}


def test_unknown_routes_are_404_and_still_need_the_token(server, fake_app):
    assert get(server, "/api/nope").status == 404
    assert post(server, "/api/reset").status == 404
    assert get(server, "/api/sync").status == 404          # actions are POST only
    assert post(server, "/api/nope", token=None).status == 401
    assert fake_app.calls == []


def test_busy_body_and_no_call_reaches_the_app(server, fake_app):
    fake_app.busy = True
    r = post(server, "/api/mute")
    assert r.status == 409 and json.loads(r.read()) == {"error": "busy"} and fake_app.calls == []


def test_a_stopping_app_is_503(server, fake_app):
    from lavalier.server import AppStopping

    async def refuse(name):
        raise AppStopping()
    fake_app.action = refuse
    r = post(server, "/api/mute")
    assert r.status == 503 and json.loads(r.read()) == {"error": "stopping"}


# --- final review fixes: an HTTP timeout never cancels the action (I1) ---

def test_a_timed_out_wait_is_504_and_the_action_still_completes(fake_app, token_path):
    import asyncio
    import threading
    from lavalier.server import ControlServer
    done = threading.Event()

    async def slow(name):
        await asyncio.sleep(0.4)
        done.set()
        return {"did": name}
    fake_app.action = slow
    s = ControlServer(fake_app, token_path=token_path, action_timeout_s=0.05)
    s.start()
    try:
        r = post(s, "/api/sync")
        assert r.status == 504 and json.loads(r.read()) == {"error": "timeout"}
        assert done.wait(5)                                  # not cancelled by the timed-out wait
    finally:
        s.stop()


def test_the_client_waits_longer_than_the_server():
    import inspect
    from lavalier import client, server
    assert inspect.signature(client.call).parameters["timeout_s"].default == 930 > server.ACTION_TIMEOUT_S


# --- Plan 3 Task 5: the window's routes ---

def test_static_index_and_assets_need_no_token_but_carry_no_data(server):
    assert get(server, "/", token=None).status == 200 and get(server, "/assets/../index.html", token=None).status == 404
def test_day_routes_return_the_view_and_400_on_a_bad_date(server_with_fixture):
    body = json.loads(get(server_with_fixture, "/api/day/2026-10-23").read())
    assert body["conversations"][0]["lines"][0]["text"] == "test test test one two three"
    assert get(server_with_fixture, "/api/day/2026-13-01").status == 400
    assert json.loads(get(server_with_fixture, "/api/day/2020-01-01").read())["conversations"] == []
def test_search_route_limits_and_marks(server_with_fixture):
    hits = json.loads(get(server_with_fixture, "/api/search?q=one%20two&limit=5").read())
    assert hits and "<mark>" in hits[0]["snippet"]
@needs_ffmpeg
def test_audio_route_requires_the_token_and_knows_410(server_with_audio):
    assert get(server_with_audio, "/api/audio/clip_x.m4a", token=None).status == 401
    r = get(server_with_audio, f"/api/audio/{CLIP}.m4a"); assert r.status == 200 and r.getheader("Content-Type") == "audio/mp4" and int(r.getheader("Content-Length")) > 1000
    server_with_audio.app.db.clear_clip_path(CLIP)
    assert get(server_with_audio, f"/api/audio/{CLIP}.m4a").status == 410
    assert get(server_with_audio, "/api/audio/clip_nope.m4a").status == 404
def test_pin_routes_flip_the_flag(server_with_fixture):
    assert json.loads(post(server_with_fixture, f"/api/pin/{CONV}").read()) == {"pinned": True}
    assert json.loads(post(server_with_fixture, f"/api/unpin/{CONV}").read()) == {"pinned": False}
    assert post(server_with_fixture, "/api/pin/c-nope").status == 404
def test_foreign_origin_is_rejected_on_data_routes(server_with_fixture):
    assert get(server_with_fixture, "/api/day/2026-10-23", origin="http://evil.test").status == 403


# --- static files ---

@pytest.fixture
def web_server(fake_app, token_path, tmp_path):
    from lavalier.server import ControlServer
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>t</title>")
    for name in ("app.js", "app.css", "logo.svg", "font.woff2", "icon.png", "favicon.ico", "data.json",
                 "app.js.map", "notes.xyz"):
        (web / "assets" / name).write_bytes(b"x")
    (tmp_path / "secret.txt").write_text("secret")
    s = ControlServer(fake_app, token_path=token_path, web_root=web)
    s.start()
    try:
        yield s
    finally:
        s.stop()


def test_index_is_no_store_html_and_ignores_the_origin(web_server):
    r = get(web_server, "/", token=None, origin="http://evil.test")
    assert r.status == 200 and r.read() == b"<!doctype html><title>t</title>"
    assert r.getheader("Cache-Control") == "no-store" and r.getheader("Content-Type").startswith("text/html")
    assert get(web_server, "/?x=1", token=None).status == 200


@pytest.mark.parametrize("name, ctype", [
    ("app.js", "text/javascript"), ("app.css", "text/css"), ("logo.svg", "image/svg+xml"),
    ("font.woff2", "font/woff2"), ("icon.png", "image/png"), ("favicon.ico", "image/x-icon"),
    ("data.json", "application/json"), ("app.js.map", "application/json"),
    ("notes.xyz", "application/octet-stream"),
])
def test_assets_carry_their_content_type(web_server, name, ctype):
    r = get(web_server, f"/assets/{name}", token=None)
    assert r.status == 200 and r.getheader("Content-Type").split(";")[0] == ctype and r.read() == b"x"
    assert r.getheader("Content-Length") == "1"


@pytest.mark.parametrize("route", [
    "/assets/../index.html", "/assets/../../secret.txt", "/assets/%2e%2e/index.html",
    "/assets/%2e%2e%2f%2e%2e%2fsecret.txt", "/assets/..%2f..%2fsecret.txt", "/assets//etc/passwd",
    "/assets/%2fetc%2fpasswd", "/assets/", "/assets/nope.js", "/assets/app.js%00.png", "/assets/..\\index.html",
    "/index.html/../..", "/secret.txt", "/../secret.txt",
])
def test_static_never_serves_outside_the_assets(web_server, route):
    r = get(web_server, route, token=None)
    assert r.status == 404 and b"secret" not in r.read()


def test_a_symlink_out_of_the_assets_is_refused(web_server, tmp_path):
    (tmp_path / "dist" / "assets" / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert get(web_server, "/assets/link.txt", token=None).status == 404


def test_static_is_get_only(web_server):
    assert post(web_server, "/", token=None).status == 404


def test_the_package_ships_a_placeholder_index(server):
    r = get(server, "/", token=None)
    assert r.status == 200 and b"<title>Lavalier</title>" in r.read()


# --- every /api/ route needs the token; the data routes check the Origin ---

@pytest.mark.parametrize("method, route", [
    ("GET", "/api/days"), ("GET", "/api/day/2026-10-23"), ("GET", "/api/starred"), ("GET", "/api/search?q=one"),
    ("GET", f"/api/audio/{CLIP}.m4a"), ("POST", f"/api/pin/{CONV}"), ("POST", f"/api/unpin/{CONV}"),
    ("GET", "/api/settings"), ("PUT", "/api/settings"),
])
def test_every_window_route_needs_the_token_and_a_local_origin(server_with_fixture, method, route):
    from conftest import _request
    assert _request(server_with_fixture, method, route, None, None, b"{}").status == 401
    assert _request(server_with_fixture, method, route, server_with_fixture.token, "http://evil.test", b"{}").status == 403


# --- data routes ---

def test_days_route_lists_the_day_with_counts(server_with_fixture):
    days = json.loads(get(server_with_fixture, "/api/days").read())
    assert days == [{"day": "2026-10-23", "speech_ms": 16000, "conversations": 1, "stars": 2, "noise_clips": 2}]


def test_starred_route_names_the_day(server_with_fixture):
    stars = json.loads(get(server_with_fixture, "/api/starred").read())
    assert [s["day"] for s in stars] == ["2026-10-23", "2026-10-23"]
    assert stars[0]["star"]["conversation_id"] == CONV and stars[0]["star"]["at_ms"] > stars[1]["star"]["at_ms"]


@pytest.mark.parametrize("route", ["/api/day/2026-1-01", "/api/day/20261023", "/api/day/nope", "/api/day/2026-02-30"])
def test_unparsable_dates_are_400(server_with_fixture, route):
    r = get(server_with_fixture, route)
    assert r.status == 400 and json.loads(r.read()) == {"error": "bad date"}


def test_search_limit_defaults_caps_and_must_be_an_integer(server_with_fixture, monkeypatch):
    from lavalier import search
    seen = []
    real = search.search

    def spy(db, q, *, limit=50):
        seen.append((q, limit))
        return real(db, q, limit=limit)
    monkeypatch.setattr(search, "search", spy)
    get(server_with_fixture, "/api/search?q=one")
    get(server_with_fixture, "/api/search?q=one&limit=5000")
    assert seen == [("one", 50), ("one", 200)]
    for bad in ("x", "1.5", "0", "-3"):
        r = get(server_with_fixture, f"/api/search?q=one&limit={bad}")
        assert r.status == 400 and "limit" in json.loads(r.read())["error"]
    assert json.loads(get(server_with_fixture, "/api/search").read()) == []


def test_search_hit_carries_the_conversation(server_with_fixture):
    hit = json.loads(get(server_with_fixture, "/api/search?q=three").read())[0]
    assert hit["day"] == "2026-10-23" and hit["conversation_id"] == CONV and hit["clip_id"] == CLIP


def test_pin_shows_in_the_day_and_marks_it_dirty(server_with_fixture):
    from datetime import date
    db = server_with_fixture.app.db
    db.mark_day_clean(date(2026, 10, 23))
    post(server_with_fixture, f"/api/pin/{CONV}")
    assert date(2026, 10, 23) in db.days_dirty()
    day = json.loads(get(server_with_fixture, "/api/day/2026-10-23").read())
    assert day["conversations"][0]["pinned"] is True
    assert json.loads(post(server_with_fixture, f"/api/pin/{CONV}").read()) == {"pinned": True}  # idempotent
    assert post(server_with_fixture, "/api/unpin/c-nope").status == 404


def test_settings_get_and_put(server_with_fixture):
    s = json.loads(get(server_with_fixture, "/api/settings").read())
    assert s["retention_days"] == 14 and "readonly" in s
    r = put(server_with_fixture, "/api/settings", {"retention_days": 30, "appearance": "dark"})
    assert r.status == 200
    body = json.loads(r.read())
    assert body["retention_days"] == 30 and body["appearance"] == "dark"
    assert json.loads(get(server_with_fixture, "/api/settings").read())["retention_days"] == 30


@pytest.mark.parametrize("patch, field", [
    ({"poll_interval_s": 5}, "poll_interval_s"), ({"retention_days": "14"}, "retention_days"),
    ({"whisper_model": "x"}, "whisper_model"), ({"nope": 1}, "nope"),
])
def test_a_bad_setting_is_400_naming_the_field(server_with_fixture, patch, field):
    r = put(server_with_fixture, "/api/settings", patch)
    body = json.loads(r.read())
    assert r.status == 400 and body["field"] == field and field in body["error"]
    assert server_with_fixture.app.cfg.retention_days == 14


@pytest.mark.parametrize("body", [b"[1, 2]", b"\"x\"", b"not json", b"", b"\xff\xfe"])
def test_a_settings_body_that_is_not_an_object_is_400(server_with_fixture, body):
    from conftest import _request
    r = _request(server_with_fixture, "PUT", "/api/settings", server_with_fixture.token, None, body)
    assert r.status == 400 and "error" in json.loads(r.read())


def test_a_settings_save_over_an_unreadable_file_is_500_and_leaves_it(server_with_fixture):
    app = server_with_fixture.app
    app.paths.config.write_text('retention_days = "x"\n')
    r = put(server_with_fixture, "/api/settings", {"retention_days": 21})
    assert r.status == 500 and json.loads(r.read())["error"].startswith("not saved: ")
    assert app.paths.config.read_text() == 'retention_days = "x"\n' and app.config_error


def test_status_carries_the_app_facts(server_with_fixture):
    import os
    s = json.loads(get(server_with_fixture, "/api/status").read())
    assert s["busy"] is False and s["app"]["pid"] == os.getpid() and isinstance(s["app"]["started_ms"], int)
    from importlib.metadata import version
    assert s["app"]["version"] == version("lavalier")


# --- audio ---

def test_audio_errors_map_to_status_codes(server_with_audio, monkeypatch):
    from lavalier import playback
    from lavalier.audio import AudioToolError

    def boom(src, dst):
        raise AudioToolError("ffmpeg failed (1): boom")
    monkeypatch.setattr(playback, "transcode", boom)
    r = get(server_with_audio, f"/api/audio/{CLIP}.m4a")
    assert r.status == 500 and json.loads(r.read()) == {"error": "ffmpeg failed (1): boom"}
    assert get(server_with_audio, f"/api/audio/{CLIP}.mp3").status == 404
    assert get(server_with_audio, "/api/audio/..%2f..%2fx.m4a").status == 404


def test_two_requests_for_one_clip_transcode_it_once(server_with_audio, monkeypatch):
    import threading
    import time
    from lavalier import playback
    calls, active, overlap = [], [0], []
    lock = threading.Lock()

    def slow(src, dst):
        with lock:
            active[0] += 1
            overlap.append(active[0])
        time.sleep(0.3)
        dst.write_bytes(b"m4a" * 400)
        calls.append(dst.name)
        with lock:
            active[0] -= 1
    monkeypatch.setattr(playback, "transcode", slow)
    replies = []
    threads = [threading.Thread(target=lambda: replies.append(get(server_with_audio, f"/api/audio/{CLIP}.m4a")))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert [r.status for r in replies] == [200, 200, 200] and all(r.read() == b"m4a" * 400 for r in replies)
    assert calls == [f"{CLIP}.m4a"] and overlap == [1]
    assert server_with_audio.app._app._audio_locks == {}          # nothing left behind


def test_different_clips_transcode_side_by_side(server_with_audio, monkeypatch):
    import threading
    from lavalier import playback
    both = threading.Barrier(2, timeout=5)

    def meet(src, dst):
        both.wait()                                                # deadlocks (BrokenBarrier) if serialised
        dst.write_bytes(b"x" * 10)
    monkeypatch.setattr(playback, "transcode", meet)
    replies = []
    ids = [CLIP, "clip_20261024T055514.111Z"]
    threads = [threading.Thread(target=lambda c=c: replies.append(get(server_with_audio, f"/api/audio/{c}.m4a")))
               for c in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(r.status for r in replies) == [200, 200]


def test_an_oversized_or_malformed_body_is_413(server):
    import http.client
    for length in (str(70000), "nope", "-5"):
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
        try:
            conn.putrequest("PUT", "/api/settings")
            conn.putheader("Authorization", f"Bearer {server.token}")
            conn.putheader("Content-Length", length)
            conn.endheaders()
            assert conn.getresponse().status == 413
        finally:
            conn.close()


# --- fix round 1 ---

@needs_ffmpeg
def test_api_replies_are_never_cached(server_with_audio):
    for route in ("/api/day/2026-10-23", "/api/search?q=one", f"/api/audio/{CLIP}.m4a", "/api/status",
                  "/api/nope"):
        r = get(server_with_audio, route)
        assert r.getheader("Cache-Control") == "no-store", route
    assert get(server_with_audio, "/api/days", token=None).getheader("Cache-Control") == "no-store"


def test_assets_are_cacheable(web_server):
    assert get(web_server, "/assets/app.js", token=None).getheader("Cache-Control") is None


def test_audio_evicted_before_it_is_read_is_410(server_with_audio, monkeypatch):
    from lavalier import playback

    def vanished(src, dst):
        pass                                              # "finished", but the sweep already removed the file
    monkeypatch.setattr(playback, "transcode", vanished)
    r = get(server_with_audio, f"/api/audio/{CLIP}.m4a")
    assert r.status == 410 and json.loads(r.read()) == {"error": "audio expired"}


def test_data_routes_are_503_while_the_app_stops(server_with_fixture):
    server_with_fixture.app._app._stopping = True
    for route in ("/api/days", "/api/day/2026-10-23", "/api/settings"):
        r = get(server_with_fixture, route)
        assert r.status == 503 and json.loads(r.read()) == {"error": "stopping"}
    assert post(server_with_fixture, f"/api/pin/{CONV}").status == 503
    assert get(server_with_fixture, f"/api/audio/{CLIP}.m4a").status == 503
    assert get(server_with_fixture, "/api/status").status == 200       # status still answers during shutdown


def test_the_request_log_never_carries_the_query_string(server, caplog):
    import logging
    with caplog.at_level(logging.DEBUG, logger="lavalier.server"):
        get(server, "/?token=secret-launch-token")
        get(server, "/api/status?token=secret-launch-token")
    assert caplog.records and "secret-launch-token" not in caplog.text and "token=" not in caplog.text
    assert "/api/status" in caplog.text
