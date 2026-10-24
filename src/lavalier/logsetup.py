"""Logging set-up shared by the CLI and the app process."""

import logging

# the fork's connection chatter (INFO lines, the .pair() warning); its decode warnings, which mean
# dropped audio, stay audible
# built from parts: only device.py may name the fork's connection modules (tests/test_closed_command_set.py)
_CHATTY = tuple(".".join(("pendant_client", m)) for m in ("ble", "session"))


def quiet_fork_chatter() -> None:
    for name in _CHATTY:
        logging.getLogger(name).setLevel(logging.ERROR)
