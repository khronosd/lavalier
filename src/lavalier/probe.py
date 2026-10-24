"""Read-only status probe: connect, read device info and status, disconnect.

`python -m lavalier.probe` prints one line, appends it with a timestamp to the probe log and
records the snapshot. It never sets the clock, mutes, or changes recording state.
"""

import asyncio
import dataclasses
import sys
from datetime import datetime

from lavalier.config import ConfigError, load_config
from lavalier.db import Database, SchemaTooNewError, now_ms
from lavalier.device import BlePendant, DeviceError, Pendant, PendantNotInRange
from lavalier.models import DeviceSnapshot
from lavalier.paths import Paths, default_root


async def read_status(pendant: Pendant, *, now_ms: int) -> DeviceSnapshot:
    async with pendant as p:
        firmware_ver, storage_instance = await p.info()
        snap = await p.status()
    return dataclasses.replace(
        snap, read_at_ms=now_ms, firmware_ver=firmware_ver, storage_instance=storage_instance
    )


def format_line(snap: DeviceSnapshot) -> str:
    partial = "false" if snap.has_all_fields else "true"
    return (
        f"state={snap.recording_state} pages={snap.pages_waiting} soc={snap.soc}% "
        f"firmware={snap.firmware_ver} partial={partial}"
    )


def main(argv=None) -> int:
    paths = Paths(default_root())
    try:
        cfg = load_config(paths.config)
    except ConfigError as e:
        print(f"probe: {e}", file=sys.stderr)
        return 1
    if not cfg.pendant_address:
        print(f"probe: pendant_address is not set in {paths.config}", file=sys.stderr)
        return 1
    pendant = BlePendant(cfg.pendant_address, scan_timeout_s=cfg.scan_timeout_s)
    try:
        snap = asyncio.run(read_status(pendant, now_ms=now_ms()))
    except PendantNotInRange:
        print("probe: pendant not in range", file=sys.stderr)
        return 2
    except DeviceError as e:
        print(f"probe: device error: {e}", file=sys.stderr)
        return 1
    line = format_line(snap)
    print(line)
    paths.ensure()
    with open(paths.logs / "probe.log", "a") as f:
        f.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {line}\n")
    db = Database(paths.db)
    try:
        db.migrate()
    except SchemaTooNewError as e:
        db.close()
        print(f"probe: {e}", file=sys.stderr)
        return 1
    with db:
        db.record_device_status(snap, source="probe", charger_signal="none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
