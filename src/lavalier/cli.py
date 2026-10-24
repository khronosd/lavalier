"""Command-line entry point."""

import asyncio
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import click

from lavalier import actions, agent, client, doctor
from lavalier.actions import another_process as _another_process
from lavalier.charger import cdc_present, read_ioreg
from lavalier.config import Config, load_config
from lavalier.dayfile import render_day, write_day
from lavalier.db import Database, SchemaTooNewError, now_ms
from lavalier.device import Pendant
from lavalier.logsetup import quiet_fork_chatter
from lavalier.lock import LockHeld, SyncLock
from lavalier.paths import Paths, default_root
from lavalier.pipeline import (
    ProcessReport, import_and_decode, process, refresh_day, retry_failed, status_summary,
    sweep_orphan_captures,
)
from lavalier.retention import sweep
from lavalier.sync import run_sync
from lavalier.transcribe import MlxWhisperTranscriber

UNMUTE_SETTLE_S = 1.0  # tests patch this to 0
SERVER_FILE = ".server.json"

# Tests monkeypatch this to hand back a FakePendant.
pendant_factory: Callable[[Config], Pendant] = actions.ble_pendant


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


def _report_lines(r: dict) -> list[str]:
    """Lines for a ProcessReport's JSON dict (from this process, the app, or the database)."""
    days = ", ".join(r["days_written"]) or "none"
    return [
        f"Loudness measured {r['loudness_measured']}",
        f"Transcribed {r['transcribed']} ({r['failed']} failed)",
        f"Day files written: {days}",
        f"Retention: {r['clips_deleted']} clips, {r['captures_deleted']} captures deleted",
    ]


def _echo_process(db: Database, report: ProcessReport) -> None:
    db.set_status("last_process", json.dumps(report.to_json_dict()))
    for line in _report_lines(report.to_json_dict()):
        click.echo(line)


def _run_process(db: Database, paths: Paths, cfg: Config) -> None:
    transcriber = MlxWhisperTranscriber(cfg.whisper_model, cfg.whisper_language)
    _echo_process(db, process(db, paths, cfg, transcriber, now_ms=now_ms()))


def _require_address(cfg: Config) -> None:
    if not cfg.pendant_address:
        raise click.ClickException("set pendant_address in config.toml")


def _lock(paths: Paths) -> SyncLock:
    return SyncLock(paths.root / ".lock")


def _cdc() -> bool:
    return cdc_present(read_ioreg())


def _device_kw(paths: Paths) -> dict:
    return {"lock": _lock(paths), "cdc_present": _cdc, "now_ms": now_ms}


def _paths_cfg() -> tuple[Paths, Config]:
    paths = Paths(default_root())
    return paths, load_config(paths.config)


def _local_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _via_app(paths: Paths, route: str) -> Optional[dict]:
    """The app's answer when the app is running (it owns the pendant), else None: run headless."""
    token = paths.root / SERVER_FILE
    if not client.app_running(token):
        return None
    try:
        return client.call(token, "POST", route)
    except client.AppBusy as e:
        raise click.ClickException(_another_process("lavalier app (busy)")) from e
    except client.AppUnavailable as e:
        raise click.ClickException(f"lavalier app: {e}") from e


_UNMUTE_TEXT = {
    "confirmed": "unmute confirmed",
    "confirmed-recording": "unmute confirmed (recording)",
    "pending": "unmute pending",
    "owner-mute-left": "left muted",
    "retried": "pending unmute retried",
}


def _sync_line(r: dict, paths: Paths) -> str:
    """The line for a SyncReport's JSON dict."""
    line = f"Sync: {r['outcome']} ({r['reason']})"
    if r["capture"] is not None:
        capture = Path(r["capture"])
        try:
            where = capture.relative_to(paths.root)
        except ValueError:
            where = capture
        line += f"; {r['messages']} messages, {r['pages']} pages -> {where}"
        if not r["capture_complete"]:
            line += " (incomplete)"
    extra = []
    if r["muted_by"]:
        extra.append(f"muted by {r['muted_by']}")
    if r["unmute"] != "n/a":
        extra.append(_UNMUTE_TEXT.get(r["unmute"], r["unmute"]))
    if extra:
        line += "; " + ", ".join(extra)
    if r["error"]:
        line += f"; error: {r['error']}"
    if r.get("orphans"):
        line += f"; {r['orphans']} stranded capture(s) imported"
    return line


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Turn pendant captures into transcripts and day files."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    quiet_fork_chatter()


def _import_line(name: str, result) -> str:
    return (f"{name}: {result.messages} messages, "
            f"{result.pages_new} new pages, {result.pages_duplicate} duplicates")


@main.command("import")
@click.argument("capture", required=False, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--incomplete", is_flag=True, help="Mark the capture as incomplete (the link dropped).")
@click.option("--orphans", is_flag=True,
              help="Import the captures a cancelled or killed drain left in captures/ (as incomplete).")
@click.option("--process", "run_process", is_flag=True, help="Decode and process after importing.")
def import_cmd(capture: Optional[Path], incomplete: bool, orphans: bool, run_process: bool) -> None:
    """Register a capture .bin and record its pages."""
    if capture is None and not orphans:
        raise click.UsageError("give a capture file, or --orphans")
    paths, cfg, db = _setup()
    with db:
        if capture is not None:
            capture_day = datetime.fromtimestamp(capture.stat().st_mtime).date()
            result, _ = import_and_decode(db, paths, capture, complete=not incomplete, capture_day=capture_day)
            click.echo(f"Imported {_import_line(capture.name, result)}")
        if orphans:
            found = sweep_orphan_captures(db, paths)
            for result in found:
                click.echo(f"Imported orphan {_import_line(Path(result.path).name.split('-', 1)[1], result)}")
            if not found:
                click.echo("No orphan captures")
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


def _echo_summary(s: dict) -> None:
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
        lines = _report_lines(json.loads(s["last_process"]))
        click.echo(f"Last process: {lines[0]}")
        for line in lines[1:]:
            click.echo(line)
    d = s["device"]
    if d is None:
        click.echo("Pendant: no status read yet")
    else:
        state = d["recording_state"] if d["has_all_fields"] else "partial status"
        click.echo(
            f"Pendant: {state} as of {d['age_s'] // 60} min ago ({d['source']}); battery {d['soc']}%, "
            f"{d['pages_waiting']} pages waiting, charger: {d['charger_signal']}, firmware {d['firmware_ver']}")
    if s["unmute_pending_since_ms"] is not None:
        click.echo(f"Pendant muted by the recorder, unmute pending since {_local_time(s['unmute_pending_since_ms'])}: "
                   "run 'lavalier unmute' or hold the button")
    elif s.get("muted_by_recorder_since_ms") is not None:
        click.echo(f"Pendant muted by the recorder since {_local_time(s['muted_by_recorder_since_ms'])}")
    elif s.get("muted_by_owner_since_ms") is not None and d is not None and d["has_all_fields"] \
            and d["recording_state"] == "NOT_RECORDING":
        click.echo(f"Pendant muted by you since {_local_time(s['muted_by_owner_since_ms'])}")
    ls = s["last_sync"]
    if ls is not None:
        click.echo(f"Last sync: {_local_time(ls['ended_ms'] or ls['started_ms'])} {ls['outcome']} ({ls['reason']})")


@main.command("status")
@click.option("--live", is_flag=True, help="Read the pendant first (read-only, the clock is not set).")
def status_cmd(live: bool) -> None:
    """Show what the state database holds."""
    if live:
        paths, cfg = _paths_cfg()
        _require_address(cfg)
        r = _via_app(paths, "/api/status-live")
        if r is None:
            paths, cfg, db = _setup()
            with db:
                r = asyncio.run(actions.status_live(db, paths, cfg, pendant_factory, **_device_kw(paths)))
        if not r["ok"]:  # the summary falls back to the last recorded read
            click.echo(f"Live read failed: {r['error']}", err=True)
        _echo_summary(r["summary"])
        return
    paths, cfg, db = _setup()
    with db:
        s = status_summary(db, paths, cfg, now_ms=now_ms())
    _echo_summary(s)


@main.command("sync")
@click.option("--dry-run", is_flag=True, help="Connect, read and decide, but change nothing on the pendant.")
def sync_cmd(dry_run: bool) -> None:
    """Drain the pendant now (the same run the background poll makes)."""
    paths, cfg = _paths_cfg()
    _require_address(cfg)
    # a dry run is not an app action; it runs here, and the device lock keeps it off the app's session
    r = None if dry_run else _via_app(paths, "/api/sync")
    if r is None:
        paths, cfg, db = _setup()
        with db:
            report = asyncio.run(run_sync(
                db, paths, cfg, pendant_factory(cfg), now_ms=now_ms, lock=_lock(paths),
                cdc_present=_cdc, dry_run=dry_run))
            if report.outcome == "locked":
                raise click.ClickException(_another_process(report.reason))
            click.echo(_sync_line(report.to_json_dict(), paths))
            processed = actions.process_after_sync(
                db, paths, cfg, report, lambda: MlxWhisperTranscriber(cfg.whisper_model, cfg.whisper_language),
                now_ms=now_ms())
        r = actions.sync_result(report, processed)
    else:
        if r["sync"]["outcome"] == "locked":
            raise click.ClickException(_another_process(r["sync"]["reason"]))
        click.echo(_sync_line(r["sync"], paths))
    if r["process"] == "scheduled":
        click.echo("Processing runs in the app; see 'lavalier status'")
    elif r["process"] is not None:
        for line in _report_lines(r["process"]):
            click.echo(line)
    if r["sync"]["outcome"] in ("error", "refused"):
        raise SystemExit(1)


def _device_action(route: str, run) -> dict:
    """The app's answer when it runs, else the headless action; a failure exits 1 with its message."""
    paths, cfg = _paths_cfg()
    r = _via_app(paths, route)
    if r is None:
        paths, cfg, db = _setup()
        with db:
            r = asyncio.run(run(db, cfg, paths))
    if not r["ok"]:
        raise click.ClickException(r["error"])
    return r


@main.command("mute")
def mute_cmd() -> None:
    """Stop recording (the owner's mute; sync leaves it alone)."""
    r = _device_action("/api/mute", lambda db, cfg, paths: actions.mute(
        db, cfg, pendant_factory, **_device_kw(paths)))
    click.echo(f"Pendant muted ({r['state']})")


@main.command("unmute")
def unmute_cmd() -> None:
    """Start recording again and clear every mute marker."""
    r = _device_action("/api/unmute", lambda db, cfg, paths: actions.unmute(
        db, cfg, pendant_factory, settle_s=UNMUTE_SETTLE_S, **_device_kw(paths)))
    click.echo(f"Pendant unmuted ({r['state']})")


@main.command("app")
def app_cmd() -> None:
    """Run the long-lived app process: the scheduler and the loopback control server."""
    from lavalier import app
    raise SystemExit(app.main([]))


@main.command("window")
def window_cmd() -> None:
    """Open the window on the running background app (journal, transcript, search, audio)."""
    from lavalier import window
    paths, cfg = _paths_cfg()
    raise SystemExit(window.main([], token_path=paths.root / SERVER_FILE, cfg=cfg, config_path=paths.config))


@main.command("install-agent")
@click.option("--program", multiple=True, help="Override the program argv (repeat per argument).")
def install_agent_cmd(program: tuple[str, ...]) -> None:
    """Install the launchd agent that runs the app from login."""
    paths, cfg = _paths_cfg()
    argv = list(program) or agent.default_program(cfg)
    try:
        plist = agent.install(paths, cfg, program=argv)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"launchctl bootstrap failed ({e.returncode})") from e
    click.echo(f"Installed {plist}")
    click.echo(f"Logs: {paths.logs / 'app.out.log'}")
    if not program and argv[1:] == ["-m", "lavalier.app"]:
        click.echo("warning: no app bundle found; the agent will run bare Python, which has no Bluetooth grant. "
                   "Build the bundle (see bundle/README.md) and run install-agent again.")


@main.command("uninstall-agent")
def uninstall_agent_cmd() -> None:
    """Remove the launchd agent."""
    click.echo("Removed" if agent.uninstall() else "Not installed")


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


if __name__ == "__main__":
    main()
