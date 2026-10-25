"""The interface every provider implements."""

from dataclasses import dataclass
from typing import Optional, Protocol

from lavalier.insights.prompt import DayText


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    recommended: bool = False
    cost_per_day: Optional[str] = None  # cost text like "about $0.20 per 3-hour day"


@dataclass(frozen=True)
class ProviderCheck:
    ok: bool
    detail: str
    models: list[ModelInfo]


class ProviderError(RuntimeError):
    """The provider's message, safe to show the owner: no key material, no stack."""


class Provider(Protocol):
    name: str
    model: str

    def summarize(self, dt: DayText) -> dict:
        """The raw JSON object from the model; parse_reply validates it."""

    def ask(self, dt: DayText, question: str) -> str: ...

    def check(self) -> ProviderCheck:
        """Reachability, key and model list; never raises."""

    def facts(self) -> dict:
        """{"sends": ..., "to": ..., "cost": ...} for the Settings sentence."""
