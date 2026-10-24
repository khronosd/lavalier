import re
from pathlib import Path

from lavalier.device import ALLOWED_SESSION_CALLS

SRC = Path(__file__).resolve().parents[1] / "src" / "lavalier"
FORBIDDEN = ("factory_reset", "reset_device", "set_server_public_key", "shipping", "debug_features", "set_bt_name", "unpair", "led_brightness", "clear_storage", "push_key")


FORK_IMPORT = re.compile(r"^\s*(from pendant_client\.(session|ble)\b|import pendant_client\.(session|ble)\b)", re.M)


def test_only_device_py_talks_to_the_fork_session():
    users = [p for p in SRC.rglob("*.py") if FORK_IMPORT.search(p.read_text())]
    assert [p.name for p in users] == ["device.py"]


def test_the_import_pattern_ignores_plain_string_mentions():
    assert not FORK_IMPORT.search('logging.getLogger("pendant_client.ble")\n')
    assert FORK_IMPORT.search("x = 1\n    from pendant_client.session import Session\n")
    assert FORK_IMPORT.search("import pendant_client.ble\n")


def test_session_calls_are_within_the_closed_set():
    calls = set(re.findall(r"_session\.(\w+)\(", (SRC / "device.py").read_text()))
    assert calls and calls <= ALLOWED_SESSION_CALLS


def test_forbidden_commands_never_appear_in_the_package():
    text = "\n".join(p.read_text() for p in SRC.rglob("*.py"))
    assert not [w for w in FORBIDDEN if w in text]
