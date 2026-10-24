"""Logging set-up shared by the CLI and the app process."""

import logging

# the fork's connection chatter (INFO lines, the .pair() warning); its decode warnings, which mean
# dropped audio, stay audible
_CHATTY = ("pendant_client.ble", "pendant_client.session")


def quiet_fork_chatter() -> None:
    for name in _CHATTY:
        logging.getLogger(name).setLevel(logging.ERROR)
