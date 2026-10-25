"""Builds the configured provider; the Settings facts and sentence; the check."""

from dataclasses import asdict
from typing import Optional

from lavalier.config import Config
from lavalier.insights import keys
from lavalier.insights.providers import anthropic, google, ollama, openai
from lavalier.insights.providers.base import Provider, ProviderCheck

KEYED = ("anthropic", "openai", "google")
SENTENCE = ("Sends each day's transcript text to {provider} once the day is complete, "
            "and whenever you press Generate or ask a question. Audio is never sent.")
DISPLAY = {"ollama": "Ollama on this Mac", "anthropic": "Anthropic", "openai": "OpenAI", "google": "Google"}
_MODULES = {"ollama": ollama, "anthropic": anthropic, "openai": openai, "google": google}


def _module(name: str):
    try:
        return _MODULES[name]
    except KeyError:
        raise ValueError(f"Unknown provider: {name!r}") from None


def _default_model(name: str, memory_gb: Optional[float]) -> str:
    if name == "ollama":  # no fixed default: the size class that fits this Mac
        return ollama.recommended_model(memory_gb if memory_gb is not None else ollama._machine_memory_gb())
    return _module(name).DEFAULT_MODEL


def make_provider(cfg: Config, *, memory_gb: Optional[float] = None) -> Optional[Provider]:
    name = cfg.insights_provider
    if not name:
        return None
    _module(name)
    model = cfg.insights_model or _default_model(name, memory_gb)
    if name == "ollama":
        return ollama.Ollama(model, memory_gb=memory_gb)
    key = keys.get_key(name)
    if name == "openai":
        return openai.OpenAI(model, key, base_url=cfg.insights_base_url)
    if name == "anthropic":
        return anthropic.Anthropic(model, key)
    return google.Google(model, key)


def provider_facts(cfg: Config) -> dict:
    name = cfg.insights_provider
    out = {"provider": name, "model": cfg.insights_model, "auto": cfg.insights_auto,
           "base_url": cfg.insights_base_url, "key_present": None, "facts": None, "models": [],
           "sentence": "", "display": ""}
    if not name:
        return out
    mod = _module(name)
    out["model"] = cfg.insights_model or _default_model(name, None)
    out["display"] = DISPLAY[name]
    out["sentence"] = SENTENCE.format(provider=DISPLAY[name])
    if name in KEYED:
        out["key_present"] = keys.has_key(name)
        out["models"] = [asdict(m) for m in mod.MODELS]
    out["facts"] = make_provider(cfg).facts()
    return out


def check(cfg: Config) -> ProviderCheck:
    try:
        p = make_provider(cfg)
    except keys.KeychainError as e:
        return ProviderCheck(False, str(e), [])
    if p is None:
        return ProviderCheck(False, "No model chosen.", [])
    return p.check()
