"""Environment checks as functions returning data; the CLI prints them and maps the exit code."""

import asyncio
import plistlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lavalier.audio import ffmpeg_available
from lavalier.config import Config
from lavalier.device import DeviceError, Pendant, PendantNotInRange
from lavalier.paths import Paths
from lavalier.probe import read_status
from lavalier.db import now_ms
from lavalier.transcribe import model_cache_dir

# Labels of other launch agents known to sync this pendant; only ever echoed from a plist found on disk.
KNOWN_PENDANT_AGENT_LABELS = ("Limitless",)
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


@dataclass(frozen=True)
class Check:
    label: str
    ok: bool
    detail: str = ""


def state_root_writable(paths: Paths) -> bool:
    probe = paths.root / ".write-test"
    try:
        paths.ensure()
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def local_checks(paths: Paths, cfg: Config, *, writable: bool) -> list[Check]:
    v = sys.version_info
    return [
        Check("python >= 3.12", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro}"),
        Check("ffmpeg", ffmpeg_available()),
        Check("state root writable", writable, str(paths.root)),
        Check("whisper model cached", model_cache_dir(cfg.whisper_model).exists(), cfg.whisper_model),
    ]


def competing_agent_plists(launch_agents_dir: Path) -> list[tuple[str, Path]]:
    """(label, plist path) of each launch agent that looks like another sync client for this pendant."""
    found: list[tuple[str, Path]] = []
    for plist in sorted(Path(launch_agents_dir).glob("*.plist")):
        try:
            data = plistlib.loads(plist.read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        label = data.get("Label")
        args = data.get("ProgramArguments")
        program = args[0] if isinstance(args, list) and args and isinstance(args[0], str) else ""
        label = label if isinstance(label, str) else ""
        if label in KNOWN_PENDANT_AGENT_LABELS or any(k in program for k in KNOWN_PENDANT_AGENT_LABELS):
            found.append((label or program or plist.stem, plist))
    return found


def competing_agents(launch_agents_dir: Path) -> list[str]:
    return [label for label, _ in competing_agent_plists(launch_agents_dir)]


def bluetooth_check(cfg: Config, pendant_factory: Callable[[Config], Pendant]) -> tuple[bool, str]:
    """A read-only status read: never sets the clock, never changes recording state."""
    if not cfg.pendant_address:
        return True, "skipped, pendant_address not set"
    try:
        snap = asyncio.run(read_status(pendant_factory(cfg), now_ms=now_ms()))
    except PendantNotInRange:
        return True, "not in range"
    except DeviceError as e:
        return False, str(e)
    state = snap.recording_state if snap.has_all_fields else "partial status"
    return True, f"{state}, {snap.pages_waiting} pages, fw {snap.firmware_ver}"
