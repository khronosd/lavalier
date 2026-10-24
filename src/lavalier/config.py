"""User configuration stored as TOML."""

import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import tomli_w


class ConfigError(Exception):
    """The config file is unreadable or has a value of the wrong type."""


@dataclass
class Config:
    pendant_address: str = ""
    retention_days: int = 14
    conversation_gap_s: int = 120
    star_window_s: int = 60
    noise_mean_db: float = -40.0
    noise_logprob: float = -0.8
    noise_min_words: int = 2
    noise_word_p: float = 0.5
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    whisper_language: str = "en"
    poll_interval_s: int = 600
    scan_timeout_s: float = 8.0
    drain_idle_timeout_s: float = 5.0
    drain_pages_threshold: int = 1000
    drain_after_hours: int = 24
    fsync_every_pages: int = 100
    require_firmware: str = ""


def _type_ok(value: object, default: object) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, type(default))


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e
    defaults = Config()
    values = {}
    for f in fields(Config):
        if f.name not in data:
            continue
        value = data[f.name]
        default = getattr(defaults, f.name)
        if not _type_ok(value, default):
            raise ConfigError(
                f"{path}: {f.name} must be {type(default).__name__}, got {type(value).__name__}"
            )
        values[f.name] = float(value) if isinstance(default, float) else value
    return Config(**values)


def save_config(cfg: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(asdict(cfg)))
