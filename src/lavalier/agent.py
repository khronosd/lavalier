"""The launchd agent that keeps the app process alive from login."""

import os
import subprocess
import sys
import plistlib
import tempfile
from collections.abc import Mapping
from pathlib import Path

from lavalier.config import Config
from lavalier.paths import Paths

LABEL = "io.github.khronosd.lavalier"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
_BUNDLE_EXE = Path("Contents") / "MacOS" / "Lavalier"


def plist_dict(*, program: list[str], log_dir: Path, env: Mapping[str, str] = os.environ) -> dict:
    d: dict = {
        "Label": LABEL,
        "ProgramArguments": list(program),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 30,
        "StandardOutPath": str(log_dir / "app.out.log"),
        "StandardErrorPath": str(log_dir / "app.err.log"),
    }
    if env.get("PENDANT_ROOT"):
        d["EnvironmentVariables"] = {"PENDANT_ROOT": env["PENDANT_ROOT"]}
    return d


def default_program(cfg: Config, *, bundle_default: Path = Path.home() / "Applications" / "Lavalier.app") -> list[str]:
    for bundle in (Path(cfg.app_bundle) if cfg.app_bundle else None, bundle_default):
        if bundle is not None and bundle.exists():
            return [str(bundle / _BUNDLE_EXE)]
    return [sys.executable, "-m", "lavalier.app"]


def _plist_path(agents_dir: Path) -> Path:
    return agents_dir / f"{LABEL}.plist"


def _target() -> str:
    return f"gui/{os.getuid()}"


def install(paths: Paths, cfg: Config, *, program: list[str] | None = None, run=subprocess.run,
            agents_dir: Path = LAUNCH_AGENTS) -> Path:
    paths.logs.mkdir(parents=True, exist_ok=True)
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist = _plist_path(agents_dir)
    data = plistlib.dumps(plist_dict(program=program or default_program(cfg), log_dir=paths.logs), sort_keys=True)
    with tempfile.NamedTemporaryFile(dir=agents_dir, prefix=".lavalier-", suffix=".tmp", delete=False) as tmp:
        tmp.write(data)
    os.replace(tmp.name, plist)
    run(["launchctl", "bootout", f"{_target()}/{LABEL}"], check=False, capture_output=True)
    run(["launchctl", "bootstrap", _target(), str(plist)], check=True)
    return plist


def uninstall(*, run=subprocess.run, agents_dir: Path = LAUNCH_AGENTS) -> bool:
    plist = _plist_path(agents_dir)
    if not plist.exists():
        return False
    run(["launchctl", "bootout", f"{_target()}/{LABEL}"], check=False, capture_output=True)
    plist.unlink()
    return True
