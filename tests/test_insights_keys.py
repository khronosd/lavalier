import keyring
import pytest

from conftest import BrokenKeyring
from lavalier.insights.keys import SERVICE, KeychainError, delete_key, get_key, has_key, set_key


pytestmark = pytest.mark.usefixtures("memory_keyring")


def test_set_get_delete_round_trip():
    set_key("anthropic", " k1 ")
    assert get_key("anthropic") == "k1" and has_key("anthropic")
    delete_key("anthropic")
    assert get_key("anthropic") is None and not has_key("anthropic")


def test_setting_an_empty_key_deletes():
    set_key("openai", "k1")
    set_key("openai", "   ")
    assert get_key("openai") is None


def test_deleting_a_missing_key_is_fine():
    delete_key("google")


def test_keychain_error_wraps_a_backend_failure_without_the_key():
    keyring.set_keyring(BrokenKeyring())
    with pytest.raises(KeychainError) as e:
        set_key("anthropic", "sk-secret-key")
    assert str(e.value).startswith("The Keychain refused:") and "sk-secret-key" not in str(e.value)
    with pytest.raises(KeychainError):
        get_key("anthropic")
    with pytest.raises(KeychainError):
        delete_key("anthropic")


def test_a_stored_empty_string_reads_as_none(memory_keyring):
    memory_keyring.store[(SERVICE, "openai")] = ""
    assert get_key("openai") is None and not has_key("openai")
