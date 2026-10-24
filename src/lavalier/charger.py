"""Infer whether the pendant is on its charger, from signals the firmware does not report.

Signals, in the order they are checked:
  usb-cdc      the pendant's USB serial device is visible in ioreg (read only, never opened)
  current      the battery current is positive
  quiet-polls  the pendant is idle and listening for two consecutive polls
"""

import subprocess
from dataclasses import dataclass
from typing import Optional

from lavalier.models import DeviceSnapshot

PRODUCT_LINE = '"USB Product Name" = "Pendant"'
VENDOR_LINE = '"USB Vendor Name" = "ZEPHYR"'
IOREG_CMD = ["ioreg", "-p", "IOUSB", "-l", "-w0"]


@dataclass(frozen=True)
class ChargerDecision:
    on_charger: bool
    signal: str  # "usb-cdc" | "current" | "quiet-polls" | "none"


def _device_blocks(ioreg_text: str):
    """Yield the property braces of each device: the `{ ... }` under one `+-o` line."""
    block = None
    for line in ioreg_text.splitlines():
        stripped = line.strip().lstrip("|").strip()
        if "+-o" in line:
            block = None
            continue
        if block is None and stripped == "{":
            block = []
            continue
        if block is not None:
            if stripped == "}":
                yield block
                block = None
            else:
                block.append(stripped)


def cdc_present(ioreg_text: str) -> bool:
    for block in _device_blocks(ioreg_text):
        if PRODUCT_LINE in block and VENDOR_LINE in block:
            return True
    return False


def read_ioreg(run=subprocess.run) -> str:
    try:
        result = run(IOREG_CMD, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def charger_decision(snap: Optional[DeviceSnapshot], *, cdc: bool, quiet_polls: int) -> ChargerDecision:
    if cdc:
        return ChargerDecision(True, "usb-cdc")
    if snap is not None and snap.has_all_fields and snap.current_ma > 0:
        return ChargerDecision(True, "current")
    if (snap is not None and snap.has_all_fields and snap.recording_state == "LISTENING"
            and quiet_polls >= 2):
        return ChargerDecision(True, "quiet-polls")
    return ChargerDecision(False, "none")
