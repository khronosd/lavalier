"""API keys in the macOS Keychain, through keyring. Errors never carry the key."""

from typing import Optional

import keyring
import keyring.errors

SERVICE = "io.github.khronosd.lavalier"


class KeychainError(RuntimeError):
    """The Keychain said no; the message names the failure, never the key."""


def _refused(e: Exception) -> KeychainError:
    detail = str(e) or type(e).__name__
    return KeychainError(f"The Keychain refused: {detail}")


def get_key(provider: str) -> Optional[str]:
    try:
        return keyring.get_password(SERVICE, provider) or None
    except Exception as e:
        raise _refused(e) from None


def delete_key(provider: str) -> None:
    try:
        keyring.delete_password(SERVICE, provider)
    except keyring.errors.PasswordDeleteError:
        pass  # missing is fine
    except Exception as e:
        raise _refused(e) from None


def set_key(provider: str, key: str) -> None:
    key = key.strip()
    if not key:
        delete_key(provider)
        return
    try:
        keyring.set_password(SERVICE, provider, key)
    except Exception as e:
        raise _refused(e) from None


def has_key(provider: str) -> bool:
    return get_key(provider) is not None
