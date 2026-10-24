"""Command-line entry point."""

import asyncio
import dataclasses
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import click

from lavalier import doctor
from lavalier.charger import cdc_present, charger_decision, read_ioreg
from lavalier.config import Config, load_config
from lavalier.dayfile import render_day, write_day
from lavalier.db import Database, SchemaTooNewError, now_ms
from lavalier.device import BlePendant, DeviceError, Pendant, PendantNotInRange
from lavalier.lock import LockHeld, SyncLock
from lavalier.models import DeviceSnapshot
from lavalier.paths import Paths, default_root
from lavalier.pipeline import (
    ProcessReport, import_and_decode, process, refresh_day, retry_failed, status_summary,
)
from lavalier.probe import read_status
from lavalier.retention import sweep
from lavalier.sync import SyncReport, after_sync, run_sync
from lavalier.transcribe import MlxWhisperTranscriber

UNMUTE_SETTLE_S = 1.0  # tests patch this to 0


def _ble_pendant(cfg: Config) -> Pendant:
    return BlePendant(cfg.pendant_address, scan_timeout_s=cfg.scan_timeout_s)


# Tests monkeypatch this to hand back a FakePendant.
pendant_factory: Callable[[Config], Pendant] = _ble_pendant


def _setup() -> tuple[Paths, Config, Database]:
    paths = Paths(default_root())
    paths.ensure()
    cfg = load_config(paths.config)
    db = Database(paths.db)
    try:
        db.migrate()
    except SchemaTooNewError as e:
        db.close()
        raise click.ClickException(str(e)) from e
    return paths, cfg, db


def _report_lines(r: ProcessReport) -> list[str]:
    days = ", ".join(d.isoformat() for d in r.days_written) or "none"
    return [
        f"Loudness measured {r.loudness_measured}",
        f"Transcribed {r.transcribed} ({r.failed} failed)",
        f"Day files written: {days}",
        f"Retention: {r.clips_deleted} clips, {r.captures_deleted} captures deleted",
    ]


def _echo_process(db: Database, report: ProcessReport) -> None:
    db.set_status("last_process", json.dumps(report.to_json_dict()))
    for line in _report_lines(report):
        click.echo(line)


def _run_process(db: Database, paths: Paths, cfg: Config) -> None:
    transcriber = MlxWhisperTranscriber(cfg.whisper_model, cfg.whisper_language)
    _echo_process(db, process(db, paths, cfg, transcriber, now_ms=now_ms()))


def _require_address(cfg: Config) -> None:
    if not cfg.pendant_address:
        raise click.ClickException("set pendant_address in config.toml")


def _lock(paths: Paths) -> SyncLock:
    return SyncLock(paths.root / ".lock")


def _another_process(holder: object) -> str:
    return f"Another process is using the pendant: {holder}"


@contextmanager
def _pendant_under_lock(paths: Paths, cfg: Config):
    """The pendant for one device command, with the device lock held for its whole duration."""
    _require_address(cfg)
    lock = _lock(paths)
    try:
        lock.acquire()
    except LockHeld as e:
        raise click.ClickException(_another_process(e)) from e
    try:
        yield pendant_factory(cfg)
    finally:
        lock.release()


def _device_call(coro):
    """Run one device coroutine; a failure is reported once, never retried."""
    try:
        return asyncio.run(coro)
    except PendantNotInRange as e:
        raise click.ClickException("Pendant not in range") from e
    except DeviceError as e:
        raise click.ClickException(f"Device error: {e}") from e


def _charger_signal(snap: DeviceSnapshot) -> str:
    return charger_decision(snap, cdc=cdc_present(read_ioreg()), quiet_polls=0).signal


def _local_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _state(snap: DeviceSnapshot) -> str:
    return snap.recording_state if snap.has_all_fields else "partial status"


_UNMUTE_TEXT = {
    "confirmed": "unmute confirmed",
    "confirmed-recording": "unmute confirmed (recording)",
    "pending": "unmute pending",
    "owner-mute-left": "left muted",
    "retried": "pending unmute retried",
}


def _sync_line(r: SyncReport, paths: Paths) -> str:
    line = f"Sync: {r.outcome} ({r.reason})"
    if r.capture is not None:
        try:
            where = r.capture.relative_to(paths.root)
        except ValueError:
            where = r.capture
        line += f"; {r.messages} messages, {r.pages} pages -> {where}"
        if not r.capture_complete:
            line += " (incomplete)"
    extra = []
    if r.muted_by:
        extra.append(f"muted by {r.muted_by}")
    if r.unmute != "n/a":
        extra.append(_UNMUTE_TEXT.get(r.unmute, r.unmute))
    if extra:
        line += "; " + ", ".join(extra)
    if r.error:
        line += f"; error: {r.error}"
    return line


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Turn pendant captures into transcripts and day files."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@main.command("import")
@click.argument("capture", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--incomplete", is_flag=True, help="Mark the capture as incomplete (the link dropped).")
@click.option("--process", "run_process", is_flag=True, help="Decode and process after importing.")
def import_cmd(capture: Path, incomplete: bool, run_process: bool) -> None:
    """Register a capture .bin and record its pages."""
    paths, cfg, db = _setup()
    capture_day = datetime.fromtimestamp(capture.stat().st_mtime).date()
    with db:
        result, _ = import_and_decode(db, paths, capture, complete=not incomplete, capture_day=capture_day)
        click.echo(
            f"Imported {capture.name}: {result.messages} messages, "
            f"{result.pages_new} new pages, {result.pages_duplicate} duplicates"
        )
        if run_process:
            _run_process(db, paths, cfg)


@main.command("process")
def process_cmd() -> None:
    """Measure loudness, transcribe, write day files, apply retention."""
    paths, cfg, db = _setup()
    with db:
        _run_process(db, paths, cfg)


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


@main.command("status")
@click.option("--live", is_flag=True, help="Read the pendant first (read-only, the clock is not set).")
def status_cmd(live: bool) -> None:
    """Show what the state database holds."""
    paths, cfg, db = _setup()
    with db:
        if live:
            _require_address(cfg)
            try:
                with _pendant_under_lock(paths, cfg) as pendant:
                    snap = _device_call(read_status(pendant, now_ms=now_ms()))
                db.record_device_status(snap, source="live", charger_signal=_charger_signal(snap))
            except click.ClickException as e:  # fall back to the last recorded read
                click.echo(f"Live read failed: {e.message}", err=True)
        s = status_summary(db, paths, cfg, now_ms=now_ms())
    click.echo(f"Days with clips: {len(s['days_with_clips'])}")
    click.echo(f"Pending transcripts: {s['pending_transcripts']}")
    click.echo(f"Failed clips: {s['failed_clips']}" + (" (retry-failed requeues them)" if s["failed_clips"] else ""))
    click.echo(f"Audio on disk: {_human_bytes(s['audio_bytes'])}")
    click.echo(f"Captures on disk: {_human_bytes(s['capture_bytes'])}")
    click.echo(f"Next deletion: {s['next_deletion'] or 'none'}")
    click.echo(f"Last import: {s['last_import'] or 'never'}")
    click.echo("pinned conversations: " + (", ".join(s["pinned"]) or "none"))
    click.echo(f"Button presses: {s['long_presses']} long, {s['double_presses']} double")
    if s["last_process"]:
        r = json.loads(s["last_process"])
        click.echo(f"Last process: Loudness measured {r['loudness_measured']}")
        click.echo(f"Transcribed {r['transcribed']} ({r['failed']} failed)")
        click.echo(f"Day files written: {', '.join(r['days_written']) or 'none'}")
        click.echo(f"Retention: {r['clips_deleted']} clips, {r['captures_deleted']} captures deleted")
    d = s["device"]
    if d is None:
        click.echo("Pendant: no status read yet")
    else:
        state = d["recording_state"] if d["has_all_fields"] else "partial status"
        click.echo(
            f"Pendant: {state} as of {d['age_s'] // 60} min ago ({d['source']}); battery {d['soc']}%, "
            f"{d['pages_waiting']} pages waiting, charger: {d['charger_signal']}, firmware {d['firmware_ver']}")
    if s["unmute_pending_since_ms"] is not None:
        click.echo(f"Unmute pending since {_local_time(s['unmute_pending_since_ms'])}: "
                   "run 'lavalier unmute' or hold the button")
    ls = s["last_sync"]
    if ls is not None:
        click.echo(f"Last sync: {_local_time(ls['ended_ms'] or ls['started_ms'])} {ls['outcome']} ({ls['reason']})")


@main.command("sync")
@click.option("--dry-run", is_flag=True, help="Connect, read and decide, but change nothing on the pendant.")
def sync_cmd(dry_run: bool) -> None:
    """Drain the pendant now (the same run the background poll makes)."""
    paths, cfg, db = _setup()
    with db:
        _require_address(cfg)
        report = asyncio.run(run_sync(
            db, paths, cfg, pendant_factory(cfg), now_ms=now_ms, lock=_lock(paths),
            cdc_present=lambda: cdc_present(read_ioreg()), dry_run=dry_run))
        if report.outcome == "locked":
            raise click.ClickException(_another_process(report.reason))
        click.echo(_sync_line(report, paths))
        if report.capture is not None:
            transcriber = MlxWhisperTranscriber(cfg.whisper_model, cfg.whisper_language)
            processed = after_sync(db, paths, cfg, report, transcriber, now_ms=now_ms())
            if processed is not None:
                _echo_process(db, processed)
    if report.outcome in ("error", "refused"):
        raise SystemExit(1)


async def _send_and_reread(pendant: Pendant, send: str, settle_s: float) -> DeviceSnapshot:
    async with pendant as p:
        firmware_ver, storage_instance = await p.info()
        await getattr(p, send)()
        await asyncio.sleep(settle_s)
        snap = await p.status()
    return dataclasses.replace(snap, read_at_ms=now_ms(), firmware_ver=firmware_ver,
                               storage_instance=storage_instance)


def _send(send: str, source: str, settle_s: float) -> tuple[Database, DeviceSnapshot]:
    paths, cfg, db = _setup()
    try:
        with _pendant_under_lock(paths, cfg) as pendant:
            snap = _device_call(_send_and_reread(pendant, send, settle_s))
        db.record_device_status(snap, source=source, charger_signal=_charger_signal(snap))
    except BaseException:
        db.close()
        raise
    return db, snap


@main.command("mute")
def mute_cmd() -> None:
    """Stop recording (the owner's mute; sync leaves it alone)."""
    db, snap = _send("stop_recording", "mute", 0)
    with db:
        if not snap.has_all_fields or snap.recording_state != "NOT_RECORDING":
            raise click.ClickException(f"Mute not confirmed: {_state(snap)}")
        db.set_status("muted_by_owner_since_ms", str(now_ms()))
    click.echo("Pendant muted (NOT_RECORDING)")


@main.command("unmute")
def unmute_cmd() -> None:
    """Start recording again and clear every mute marker."""
    db, snap = _send("start_recording", "unmute", UNMUTE_SETTLE_S)
    with db:
        state = _state(snap)
        if state not in ("LISTENING", "RECORDING"):
            still = f"still {state}" if state == "NOT_RECORDING" else state
            raise click.ClickException(f"Unmute not confirmed: {still}")
        for key in ("unmute_pending_since_ms", "muted_by_recorder_since_ms", "muted_by_owner_since_ms"):
            db.clear_status(key)
    click.echo(f"Pendant unmuted ({state})")


@main.command("doctor")
@click.option("--download-model", is_flag=True, help="Fetch the whisper model (the only networked action).")
@click.option("--no-device", is_flag=True, help="Skip the connection to the pendant.")
def doctor_cmd(download_model: bool, no_device: bool) -> None:
    """Check the environment."""
    paths = Paths(default_root())
    # Check the state root first: an unwritable root is a FAIL line, not a traceback.
    writable = doctor.state_root_writable(paths)
    cfg = load_config(paths.config)
    if download_model:
        # huggingface_hub reads HF_HUB_OFFLINE at import, and this process already imported it
        # offline; a child process with the variable removed is the only way to go online.
        click.echo(f"Downloading {cfg.whisper_model} ...")
        env = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
        subprocess.run(
            [sys.executable, "-c", "import huggingface_hub,sys; huggingface_hub.snapshot_download(sys.argv[1])",
             cfg.whisper_model],
            env=env, check=False)
    checks = doctor.local_checks(paths, cfg, writable=writable)
    if not no_device and writable:
        lock = _lock(paths)
        try:
            lock.acquire()
        except LockHeld as e:
            checks.append(doctor.Check("pendant reachable", True, f"skipped, in use by {e}"))
        else:
            try:
                good, detail = doctor.bluetooth_check(cfg, pendant_factory)
            finally:
                lock.release()
            checks.append(doctor.Check("pendant reachable", good, detail))
    for c in checks:
        click.echo(f"{'ok  ' if c.ok else 'FAIL'} {c.label}{': ' + c.detail if c.detail else ''}")
    for label, plist in doctor.competing_agent_plists(doctor.LAUNCH_AGENTS_DIR):
        click.echo(f"WARN another launch agent syncs this pendant: {label} ({plist}); unload it before the first drain")
    if not all(c.ok for c in checks):
        raise SystemExit(1)


@main.command("retry-failed")
def retry_failed_cmd() -> None:
    """Requeue failed clips so the next process retries them."""
    paths, cfg, db = _setup()
    with db:
        n = retry_failed(db)
    click.echo(f"Requeued {n} failed clips; run process to retry them")


@main.command("day")
@click.argument("day", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--open", "open_file", is_flag=True, help="Write the day file and open it.")
@click.option("--keep-noise", is_flag=True, help="Append the dropped noise clips.")
def day_cmd(day: datetime, open_file: bool, keep_noise: bool) -> None:
    """Print a day file."""
    if open_file and keep_noise:
        raise click.UsageError("--keep-noise only applies when printing")
    paths, cfg, db = _setup()
    d = day.date()
    with db:
        if open_file:
            refresh_day(db, d, cfg)
            out = write_day(db, paths, d, cfg, now_ms=now_ms())
            subprocess.run(["open", str(out)], check=False)
        else:
            click.echo(render_day(db, d, cfg, now_ms=now_ms(), keep_noise=keep_noise), nl=False)


def _find_conversation_day(db: Database, conversation_id: str) -> date:
    for d in db.days_with_clips():
        if any(c.conversation_id == conversation_id for c in db.conversations_for_day(d)):
            return d
    raise click.ClickException(f"no such conversation: {conversation_id}")


def _pin(conversation_id: str, pin: bool) -> None:
    paths, cfg, db = _setup()
    with db:
        d = _find_conversation_day(db, conversation_id)
        (db.pin if pin else db.unpin)(conversation_id)
        refresh_day(db, d, cfg)
        write_day(db, paths, d, cfg, now_ms=now_ms())
    click.echo(f"{'pinned' if pin else 'unpinned'} {conversation_id}")


@main.command("pin")
@click.argument("conversation_id")
def pin_cmd(conversation_id: str) -> None:
    """Keep a conversation's audio."""
    _pin(conversation_id, True)


@main.command("unpin")
@click.argument("conversation_id")
def unpin_cmd(conversation_id: str) -> None:
    """Release a pinned conversation."""
    _pin(conversation_id, False)


@main.command("retention")
@click.option("--now", "run_now", is_flag=True, help="Run the retention sweep now.")
def retention_cmd(run_now: bool) -> None:
    """Apply the audio retention window."""
    if not run_now:
        raise click.UsageError("pass --now to run the sweep")
    paths, cfg, db = _setup()
    with db:
        clips, caps = sweep(db, paths, cfg, now_ms=now_ms())
    click.echo(f"Retention: {clips} clips, {caps} captures deleted")
