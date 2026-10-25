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


def _build(cfg: Config, key: Optional[str], memory_gb: Optional[float]) -> Provider:
    name = cfg.insights_provider
    mod = _module(name)
    if name == "ollama":
        p = ollama.Ollama(cfg.insights_model, memory_gb=memory_gb)
        if not cfg.insights_model:  # no fixed default: the size class that fits this Mac
            p.model = ollama.recommended_model(p.memory_gb)
        return p
    model = cfg.insights_model or mod.DEFAULT_MODEL
    if name == "openai":
        return openai.OpenAI(model, key, base_url=cfg.insights_base_url)
    if name == "anthropic":
        return anthropic.Anthropic(model, key)
    return google.Google(model, key)


def make_provider(cfg: Config, *, memory_gb: Optional[float] = None) -> Optional[Provider]:
    name = cfg.insights_provider
    if not name:
        return None
    _module(name)
    return _build(cfg, keys.get_key(name) if name in KEYED else None, memory_gb)


def provider_facts(cfg: Config) -> dict:
    name = cfg.insights_provider
    out = {"provider": name, "model": cfg.insights_model, "auto": cfg.insights_auto,
           "base_url": cfg.insights_base_url, "key_present": None, "keychain_error": None,
           "facts": None, "models": [], "sentence": "", "display": ""}
    if not name:
        return out
    mod = _module(name)
    out["display"] = DISPLAY[name]
    out["sentence"] = SENTENCE.format(provider=DISPLAY[name])
    key = None
    if name in KEYED:
        out["models"] = [asdict(m) for m in mod.MODELS]
        try:
            key = keys.get_key(name)  # one Keychain read; each can prompt
            out["key_present"] = key is not None
        except keys.KeychainError as e:
            out["keychain_error"] = str(e)
    p = _build(cfg, key, None)
    out["model"] = p.model
    out["facts"] = p.facts()
    return out


def check(cfg: Config) -> ProviderCheck:
    try:
        p = make_provider(cfg)
    except (keys.KeychainError, ValueError) as e:
        return ProviderCheck(False, str(e), [])
    if p is None:
        return ProviderCheck(False, "No model chosen.", [])
    return p.check()
