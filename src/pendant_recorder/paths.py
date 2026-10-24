"""State-root directory layout."""

import os
from dataclasses import dataclass
from pathlib import Path


def default_root() -> Path:
    env = os.environ.get("PENDANT_ROOT")
    return Path(env) if env else Path.home() / "Pendant"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.toml"

    @property
    def db(self) -> Path:
        return self.root / "state.sqlite"

    @property
    def captures(self) -> Path:
        return self.root / "captures"

    @property
    def audio(self) -> Path:
        return self.root / "audio"

    @property
    def days(self) -> Path:
        return self.root / "days"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        for d in (self.root, self.captures, self.audio, self.days, self.logs):
            d.mkdir(parents=True, exist_ok=True)
