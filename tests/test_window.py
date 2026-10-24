import sys

import pytest

from lavalier.config import Config, load_config, save_config
from lavalier.server import ControlServer
from lavalier.window import NOT_RUNNING, main


class FakeEvents:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self, size):
        self.width, self.height = size
        self.events = type("E", (), {})()
        self.events.closed = FakeEvents()
        self.events.resized = FakeEvents()


class FakeWebview:
    """Records create_window/start; start() 'closes' the window, optionally at a final size."""

    def __init__(self, final_size=None, while_open=None):
        self.final_size = final_size
        self.while_open = while_open  # called while the window is open: another writer, say
        self.created = []
        self.started = False
        self.window = None

    def create_window(self, title, **kwargs):
        self.created.append((title, kwargs))
        self.window = FakeWindow((kwargs["width"], kwargs["height"]))
        return self.window

    def start(self, *a, **kw):
        self.started = True
        if self.while_open:
            self.while_open()
        if self.final_size:
            for h in self.window.events.resized.handlers:
                h(*self.final_size)
        self.window.width = self.window.height = None  # gone by `closed`, as on macOS
        for h in self.window.events.closed.handlers:
            h()


@pytest.fixture
def window_server(fake_app, tmp_path):
    s = ControlServer(fake_app, token_path=tmp_path / ".server.json")
    s.start()
    try:
        yield s
    finally:
        s.stop()


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(), path)
    return path


def test_window_refuses_when_the_app_is_not_running(tmp_path, capsys):
    fake = FakeWebview()
    assert main(webview=fake, token_path=tmp_path / ".server.json", cfg=Config()) == 1
    assert NOT_RUNNING in capsys.readouterr().err and fake.created == []
    assert not (tmp_path / ".server.json").exists()


def test_window_opens_the_app_page_with_the_token(window_server):
    fake = FakeWebview()
    assert main(webview=fake, token_path=window_server.token_path, cfg=Config(window_size="1000x700")) == 0
    (title, kwargs), = fake.created
    assert title == "Lavalier"
    assert kwargs["url"] == f"http://127.0.0.1:{window_server.port}/?token={window_server.token}"
    assert (kwargs["width"], kwargs["height"]) == (1000, 700)
    assert kwargs["min_size"] == (820, 560) and kwargs["text_select"] is True
    assert set(kwargs) == {"url", "width", "height", "min_size", "text_select"}
    assert fake.started


def test_window_saves_its_size_on_close(window_server, config_file):
    fake = FakeWebview(final_size=(1280, 800))
    assert main(webview=fake, token_path=window_server.token_path, cfg=load_config(config_file),
                config_path=config_file) == 0
    assert load_config(config_file).window_size == "1280x800"


def test_a_failed_save_on_close_is_logged_and_does_not_change_the_exit_code(window_server, tmp_path, capsys):
    fake = FakeWebview(final_size=(1280, 800))
    (tmp_path / "file").write_text("x")
    bad = tmp_path / "file" / "config.toml"  # a parent that is a file: the write fails
    assert main(webview=fake, token_path=window_server.token_path, cfg=Config(), config_path=bad) == 0
    assert "window size" in capsys.readouterr().err


def test_window_without_pywebview_says_so(window_server, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "webview", None)  # makes `import webview` raise ImportError
    assert main(token_path=window_server.token_path, cfg=Config()) == 1
    assert "pywebview is not installed; reinstall with 'pip install -e .'" in capsys.readouterr().err


def test_importing_the_window_module_does_not_import_pywebview():
    import subprocess
    out = subprocess.run([sys.executable, "-c", "import lavalier.window, sys; print('webview' in sys.modules)"],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_cli_window_command_passes_the_resolved_config_and_token(cli_env, monkeypatch):
    from click.testing import CliRunner
    from lavalier import cli, window
    seen = {}
    monkeypatch.setattr(window, "main", lambda argv=None, **kw: seen.update(kw) or 0)
    r = CliRunner().invoke(cli.main, ["window"])
    assert r.exit_code == 0
    assert seen["token_path"] == cli_env.root.root / ".server.json"
    assert seen["config_path"] == cli_env.root.config and seen["cfg"].pendant_address == "FAKE"


def test_an_unchanged_size_is_not_saved(window_server, config_file):
    before = config_file.read_text()
    assert main(webview=FakeWebview(), token_path=window_server.token_path, cfg=load_config(config_file),
                config_path=config_file) == 0
    assert config_file.read_text() == before


@pytest.mark.parametrize("bad", ["big", "1120"])
def test_a_malformed_window_size_falls_back_with_a_warning(window_server, capsys, bad):
    fake = FakeWebview()
    assert main(webview=fake, token_path=window_server.token_path, cfg=Config(window_size=bad)) == 0
    (_, kwargs), = fake.created
    assert (kwargs["width"], kwargs["height"]) == (1120, 720)
    assert capsys.readouterr().err.count("window_size") == 1


def test_the_default_state_root_is_never_the_real_one(tmp_path):
    from pathlib import Path
    from lavalier.paths import default_root
    assert tmp_path in default_root().parents and Path.home() / "Pendant" != default_root()


def test_an_injected_cfg_without_a_config_path_is_never_saved(window_server, tmp_path, capsys):
    from lavalier.paths import default_root
    fake = FakeWebview(final_size=(1280, 800))
    assert main(webview=fake, token_path=window_server.token_path, cfg=Config(window_size="1000x700")) == 0
    assert not (default_root() / "config.toml").exists()
    assert "no config path" in capsys.readouterr().err


def test_closing_keeps_settings_another_writer_saved_while_open(window_server, config_file):
    from lavalier import settings
    cfg = load_config(config_file)
    second = lambda: settings.apply(load_config(config_file), {"retention_days": 21, "appearance": "dark"},
                                    config_file)
    fake = FakeWebview(final_size=(1280, 800), while_open=second)
    assert main(webview=fake, token_path=window_server.token_path, cfg=cfg, config_path=config_file) == 0
    saved = load_config(config_file)
    assert (saved.retention_days, saved.appearance, saved.window_size) == (21, "dark", "1280x800")


def test_an_unreadable_config_on_close_is_logged_and_left_alone(window_server, config_file, capsys):
    fake = FakeWebview(final_size=(1280, 800), while_open=lambda: config_file.write_text("not = [toml\n"))
    assert main(webview=fake, token_path=window_server.token_path, cfg=load_config(config_file),
                config_path=config_file) == 0
    assert "could not save the window size" in capsys.readouterr().err
    assert config_file.read_text() == "not = [toml\n"
