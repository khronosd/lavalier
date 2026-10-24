"""The whitelisted, validated subset of the configuration the window may read and write."""

import re
from dataclasses import fields, replace
from pathlib import Path

from lavalier.config import Config, _type_ok, save_config
from lavalier.paths import Paths

EDITABLE = ("pendant_address", "retention_days", "poll_interval_s", "drain_pages_threshold", "drain_after_hours",
            "require_firmware", "whisper_language", "appearance", "window_size")

# Kept equal to bundle.build_app.BUNDLE_ID by a test; the bundle builder runs outside the package.
BUNDLE_ID = "io.github.khronosd.lavalier"

APPEARANCES = {"system", "light", "dark"}
_WINDOW_SIZE = re.compile(r"^\d{3,4}x\d{3,4}$")


class SettingsError(ValueError):
    """A settings patch was refused; the message names the field."""


def read_settings(cfg: Config, paths: Paths) -> dict:
    out = {name: getattr(cfg, name) for name in EDITABLE}
    out["readonly"] = {"state_root": str(paths.root), "whisper_model": cfg.whisper_model, "bundle_id": BUNDLE_ID}
    return out


def _check_value(name: str, value) -> None:
    if name == "appearance" and value not in APPEARANCES:
        raise SettingsError(f"appearance must be one of {', '.join(sorted(APPEARANCES))}")
    if name == "retention_days" and value < 0:
        raise SettingsError("retention_days must be 0 or more")
    if name == "poll_interval_s" and value < 60:
        raise SettingsError("poll_interval_s must be at least 60")
    if name == "window_size" and not _WINDOW_SIZE.match(value):
        raise SettingsError("window_size must look like 1120x720")


def apply(cfg: Config, patch: dict, path: Path) -> Config:
    defaults = Config()
    known = {f.name for f in fields(Config)}
    for name, value in patch.items():
        if name not in EDITABLE:
            raise SettingsError(f"{name} is not an editable setting" if name in known else f"unknown setting {name}")
        if not _type_ok(value, getattr(defaults, name)):
            raise SettingsError(f"{name} must be {type(getattr(defaults, name)).__name__}, got {type(value).__name__}")
        _check_value(name, value)
    new_cfg = replace(cfg, **patch)
    save_config(new_cfg, path)
    return new_cfg
