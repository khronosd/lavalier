"""`lavalier window`: a native window on the running background app's page.

A separate process from the app, so a webview crash never takes the recorder down.
"""

import sys
from pathlib import Path
from typing import Optional

from lavalier import client, settings
from lavalier.config import Config, load_config
from lavalier.paths import Paths, default_root

NOT_RUNNING = "The background app is not running. Start it with 'lavalier app' or install it with 'lavalier install-agent'."
NO_WEBVIEW = "pywebview is not installed; reinstall with 'pip install -e .'"
MIN_SIZE = (820, 560)


def _size(text: str) -> tuple[int, int]:
    w, h = text.split("x")
    return int(w), int(h)


def _size_or_default(text: str) -> tuple[int, int]:
    try:
        return _size(text)
    except ValueError:
        print(f"window_size {text!r} in config.toml is not like 1120x720; using {Config().window_size}",
              file=sys.stderr)
        return _size(Config().window_size)


def main(argv=None, *, webview=None, token_path: Optional[Path] = None, cfg: Optional[Config] = None,
         config_path: Optional[Path] = None) -> int:
    paths = Paths(default_root())
    token_path = Path(token_path) if token_path is not None else paths.root / ".server.json"
    if cfg is None:
        config_path = Path(config_path) if config_path is not None else paths.config
        cfg = load_config(config_path)
    elif config_path is not None:
        config_path = Path(config_path)
    # else: an injected cfg without its path is never saved (no guessing the state root)
    if not client.app_running(token_path):
        print(NOT_RUNNING, file=sys.stderr)
        return 1
    if webview is None:
        try:
            import webview
        except ImportError:
            print(NO_WEBVIEW, file=sys.stderr)
            return 1
    info = client._token(token_path)
    width, height = _size_or_default(cfg.window_size)
    last = {"size": (width, height)}
    window = webview.create_window(
        "Lavalier", url=f"http://127.0.0.1:{int(info['port'])}/?token={info['token']}",
        width=width, height=height, min_size=MIN_SIZE, text_select=True)

    def on_resized(w, h) -> None:
        last["size"] = (int(w), int(h))

    def on_closed(*_args) -> None:
        # Never read window.width/height here: on macOS the window is already gone when `closed` fires.
        if last["size"] == (width, height):
            return
        if config_path is None:
            print("could not save the window size: no config path was given", file=sys.stderr)
            return
        try:
            settings.apply(cfg, {"window_size": "%dx%d" % last["size"]}, config_path)
        except (settings.SettingsError, OSError) as e:
            print(f"could not save the window size: {e}", file=sys.stderr)

    window.events.resized += on_resized
    window.events.closed += on_closed
    webview.start()
    return 0
