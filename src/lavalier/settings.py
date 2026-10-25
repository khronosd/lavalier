"""The whitelisted, validated subset of the configuration the window may read and write."""

import re
from dataclasses import fields, replace
from pathlib import Path

from lavalier.config import Config, _type_ok, load_config, save_config
from lavalier.paths import Paths

EDITABLE = ("pendant_address", "retention_days", "poll_interval_s", "drain_pages_threshold", "drain_after_hours",
            "require_firmware", "whisper_language", "appearance", "window_size",
            "insights_provider", "insights_model", "insights_base_url", "insights_auto")

# Kept equal to bundle.build_app.BUNDLE_ID by a test; the bundle builder runs outside the package.
BUNDLE_ID = "io.github.khronosd.lavalier"

PROVIDERS = ("", "ollama", "anthropic", "openai", "google")
APPEARANCES = {"system", "light", "dark"}
_WINDOW_SIZE = re.compile(r"^\d{3,4}x\d{3,4}$")
_LANGUAGE = re.compile(r"[a-z]{2,3}")  # a whisper language code; matched whole
MAX_RETENTION_DAYS = 36500


class SettingsError(ValueError):
    """A settings patch was refused; the message names the field, and so does `field`."""

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


def read_settings(cfg: Config, paths: Paths) -> dict:
    out = {name: getattr(cfg, name) for name in EDITABLE}
    out["readonly"] = {"state_root": str(paths.root), "whisper_model": cfg.whisper_model, "bundle_id": BUNDLE_ID}
    return out


def _check_value(name: str, value) -> None:
    if name == "appearance" and value not in APPEARANCES:
        raise SettingsError(f"appearance must be one of {', '.join(sorted(APPEARANCES))}", name)
    if name == "retention_days" and not 0 <= value <= MAX_RETENTION_DAYS:
        raise SettingsError(f"retention_days must be from 0 to {MAX_RETENTION_DAYS}", name)
    if name == "drain_pages_threshold" and value < 1:
        raise SettingsError("drain_pages_threshold must be at least 1", name)
    if name == "drain_after_hours" and value < 0:
        raise SettingsError("drain_after_hours must be 0 or more", name)
    if name == "whisper_language" and not _LANGUAGE.fullmatch(value):
        raise SettingsError("whisper_language must be a 2 or 3 letter code like en", name)
    if name == "poll_interval_s" and value < 60:
        raise SettingsError("poll_interval_s must be at least 60", name)
    if name == "window_size" and not _WINDOW_SIZE.fullmatch(value):
        raise SettingsError("window_size must look like 1120x720", name)
    if name == "insights_provider" and value not in PROVIDERS:
        raise SettingsError(f"insights_provider must be one of {', '.join(repr(p) for p in PROVIDERS)}", name)
    if name == "insights_base_url" and value and (value in ("http://", "https://") or not value.startswith(("http://", "https://"))):
        raise SettingsError("insights_base_url must be empty or start with http:// or https://", name)


def apply(cfg: Config, patch: dict, path: Path) -> Config:
    """Validate `patch`, apply only its keys to the file at `path` as it is now, save, return the result.

    Two writers (the app's Settings page, the window saving its size) each keep a Config from an earlier
    read; patching the file rather than that copy keeps one from reverting what the other saved. `cfg`
    is the base only while no file exists yet. An unreadable file raises ConfigError and is left alone."""
    defaults = Config()
    known = {f.name for f in fields(Config)}
    for name, value in patch.items():
        if name not in EDITABLE:
            raise SettingsError(f"{name} is not an editable setting" if name in known else f"unknown setting {name}",
                                name)
        if not _type_ok(value, getattr(defaults, name)):
            raise SettingsError(f"{name} must be {type(getattr(defaults, name)).__name__}, got {type(value).__name__}",
                                name)
        _check_value(name, value)
    base = load_config(path) if path.exists() else cfg
    new_cfg = replace(base, **patch)
    save_config(new_cfg, path)
    return new_cfg
