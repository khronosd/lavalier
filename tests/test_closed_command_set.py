import re
from pathlib import Path

from lavalier.device import ALLOWED_SESSION_CALLS

SRC = Path(__file__).resolve().parents[1] / "src" / "lavalier"
FORBIDDEN = ("factory_reset", "reset_device", "set_server_public_key", "shipping", "debug_features", "set_bt_name", "unpair", "led_brightness", "clear_storage", "push_key")


def test_only_device_py_talks_to_the_fork_session():
    users = [p for p in SRC.rglob("*.py") if re.search(r"pendant_client\.(session|ble)\b", p.read_text())]
    assert [p.name for p in users] == ["device.py"]


def test_session_calls_are_within_the_closed_set():
    calls = set(re.findall(r"_session\.(\w+)\(", (SRC / "device.py").read_text()))
    assert calls and calls <= ALLOWED_SESSION_CALLS


def test_forbidden_commands_never_appear_in_the_package():
    text = "\n".join(p.read_text() for p in SRC.rglob("*.py"))
    assert not [w for w in FORBIDDEN if w in text]
