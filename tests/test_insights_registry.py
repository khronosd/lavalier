import json
from dataclasses import asdict

import keyring
import pytest

from lavalier.config import Config
from lavalier.insights import keys
from lavalier.insights.providers import anthropic as anth
from lavalier.insights.providers import ollama
from lavalier.insights.providers.base import ProviderCheck
from lavalier.insights.registry import check, make_provider, provider_facts
from conftest import BrokenKeyring


def test_make_provider_none_without_a_provider():
    assert make_provider(Config()) is None


def test_make_provider_uses_the_default_model_and_the_saved_key():
    keys.set_key("anthropic", "k1")
    p = make_provider(Config(insights_provider="anthropic"))
    assert p.model == anth.DEFAULT_MODEL == "claude-opus-5-5" and p._client is not None


def test_make_provider_without_a_key_and_with_a_chosen_model():
    p = make_provider(Config(insights_provider="google", insights_model="m1"))
    assert p.model == "m1" and p._client is None


def test_make_provider_ollama_and_openai_base_url():
    p = make_provider(Config(insights_provider="ollama"), memory_gb=16)
    assert p.name == "ollama" and p.model == ollama.recommended_model(16)
    p = make_provider(Config(insights_provider="openai", insights_base_url="http://x/v1"))
    assert p.base_url == "http://x/v1"


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        make_provider(Config(insights_provider="nope"))


def test_provider_facts_has_the_sentence_and_hides_the_key():
    keys.set_key("anthropic", "k1")
    f = provider_facts(Config(insights_provider="anthropic"))
    assert f["sentence"].startswith("Sends each day's transcript text to Anthropic")
    assert "k1" not in json.dumps(f) and f["key_present"] is True
    assert f["model"] == "claude-opus-5-5" and f["models"][0]["id"] == "claude-opus-5-5" and f["facts"]


def test_provider_facts_without_a_provider_or_for_ollama():
    f = provider_facts(Config())
    assert f["sentence"] == "" and f["facts"] is None and f["key_present"] is None
    o = provider_facts(Config(insights_provider="ollama"))
    assert o["key_present"] is None and o["models"] == [] and o["display"] == "Ollama on this Mac"


def test_check_without_a_provider():
    assert check(Config()).detail == "No model chosen."


def test_check_never_raises_on_a_keychain_failure():
    keyring.set_keyring(BrokenKeyring())
    r = check(Config(insights_provider="anthropic"))
    assert isinstance(r, ProviderCheck) and not r.ok and r.detail.startswith("The Keychain refused")


def test_check_with_an_unknown_provider_does_not_raise():
    r = check(Config(insights_provider="nope"))
    assert not r.ok and "nope" in r.detail


def test_check_results_carry_no_key(monkeypatch):
    keys.set_key("anthropic", "sk-secret-k9")
    r = check(Config(insights_provider="anthropic"))
    assert "sk-secret-k9" not in json.dumps(asdict(r))


def test_provider_facts_survives_a_locked_keychain():
    keyring.set_keyring(BrokenKeyring())
    f = provider_facts(Config(insights_provider="anthropic"))
    assert f["key_present"] is None and f["keychain_error"].startswith("The Keychain refused")
    assert f["sentence"] and f["facts"] and f["models"]


def test_provider_facts_reads_the_keychain_once(memory_keyring):
    keys.set_key("openai", "k1")
    calls = []
    orig = memory_keyring.get_password
    memory_keyring.get_password = lambda s, u: (calls.append(u), orig(s, u))[1]
    f = provider_facts(Config(insights_provider="openai"))
    assert f["key_present"] is True and f["keychain_error"] is None and len(calls) == 1


# --- final fix wave: the endpoint is named and has its own key (R23, R24)

ENDPOINT = Config(insights_provider="openai", insights_base_url="https://llm.example.net/v1")


def test_an_endpoint_is_named_as_the_endpoint_not_openai():
    from lavalier.insights.registry import display_name
    assert display_name(ENDPOINT) == "the endpoint at llm.example.net"
    assert display_name(Config(insights_provider="openai")) == "OpenAI"
    f = provider_facts(ENDPOINT)
    assert f["display"] == "the endpoint at llm.example.net"
    assert f["sentence"].startswith("Sends each day's transcript text to the endpoint at llm.example.net once")
    assert "OpenAI" not in f["sentence"]


def test_each_endpoint_has_its_own_keychain_account():
    from lavalier.insights.registry import key_account
    assert key_account(Config(insights_provider="openai")) == "openai"
    assert key_account(ENDPOINT) == "openai@llm.example.net"
    assert key_account(Config(insights_provider="anthropic", insights_base_url="https://x/v1")) == "anthropic"
    assert key_account(ENDPOINT, "anthropic") == "anthropic"
    assert key_account(Config(insights_provider="anthropic", insights_base_url="https://x/v1"), "openai") == "openai@x"


def test_changing_the_base_url_changes_the_account_read(memory_keyring):
    keys.set_key("openai", "sk-openai")
    assert provider_facts(Config(insights_provider="openai"))["key_present"] is True
    assert provider_facts(ENDPOINT)["key_present"] is False          # the OpenAI key is not sent elsewhere
    assert make_provider(ENDPOINT)._client is None
    keys.set_key("openai@llm.example.net", "sk-endpoint")
    assert provider_facts(ENDPOINT)["key_present"] is True
    assert make_provider(ENDPOINT)._client.api_key == "sk-endpoint"
    assert make_provider(Config(insights_provider="openai"))._client.api_key == "sk-openai"
