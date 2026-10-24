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


def main(argv=None, *, webview=None, token_path: Optional[Path] = None, cfg: Optional[Config] = None,
         config_path: Optional[Path] = None) -> int:
    paths = Paths(default_root())
    token_path = Path(token_path) if token_path is not None else paths.root / ".server.json"
    config_path = Path(config_path) if config_path is not None else paths.config
    if cfg is None:
        cfg = load_config(config_path)
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
    width, height = _size(cfg.window_size)
    window = webview.create_window(
        "Lavalier", url=f"http://127.0.0.1:{int(info['port'])}/?token={info['token']}",
        width=width, height=height, min_size=MIN_SIZE, text_select=True)

    def on_closed(*_args) -> None:
        try:
            settings.apply(cfg, {"window_size": f"{window.width}x{window.height}"}, config_path)
        except (settings.SettingsError, OSError) as e:
            print(f"could not save the window size: {e}", file=sys.stderr)

    window.events.closed += on_closed
    webview.start()
    return 0
