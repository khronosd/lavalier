import keyring
import keyring.backend
import keyring.errors
import pytest

from lavalier.insights.keys import KeychainError, delete_key, get_key, has_key, set_key


class InMemory(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.store[(service, username)]


class Broken(InMemory):
    def get_password(self, service, username):
        raise keyring.errors.KeyringError("locked")

    def set_password(self, service, username, password):
        raise keyring.errors.KeyringError("locked")

    def delete_password(self, service, username):
        raise RuntimeError("backend exploded")


@pytest.fixture(autouse=True)
def memory_keyring():
    old = keyring.get_keyring()
    keyring.set_keyring(InMemory())
    yield
    keyring.set_keyring(old)


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
    keyring.set_keyring(Broken())
    with pytest.raises(KeychainError) as e:
        set_key("anthropic", "sk-secret-key")
    assert str(e.value).startswith("The Keychain refused:") and "sk-secret-key" not in str(e.value)
    with pytest.raises(KeychainError):
        get_key("anthropic")
    with pytest.raises(KeychainError):
        delete_key("anthropic")
