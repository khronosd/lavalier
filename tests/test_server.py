import json

from conftest import get, post


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
