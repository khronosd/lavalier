"""Command-line entry point."""

import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import click

from pendant_recorder.audio import ffmpeg_available
from pendant_recorder.clips import decode_new_pages
from pendant_recorder.config import Config, load_config
from pendant_recorder.dayfile import render_day, write_day
from pendant_recorder.db import Database, now_ms
from pendant_recorder.pages import import_capture
from pendant_recorder.paths import Paths, default_root
from pendant_recorder.pipeline import ProcessReport, process, status_summary
from pendant_recorder.retention import sweep
from pendant_recorder.transcribe import MlxWhisperTranscriber


def _setup() -> tuple[Paths, Config, Database]:
    paths = Paths(default_root())
    paths.ensure()
    cfg = load_config(paths.config)
    db = Database(paths.db)
    db.migrate()
    return paths, cfg, db


def _report_lines(r: ProcessReport) -> list[str]:
    days = ", ".join(d.isoformat() for d in r.days_written) or "none"
    return [
        f"Loudness measured {r.loudness_measured}",
        f"Transcribed {r.transcribed} ({r.failed} failed)",
        f"Day files written: {days}",
        f"Retention: {r.clips_deleted} clips, {r.captures_deleted} captures deleted",
    ]


def _run_process(db: Database, paths: Paths, cfg: Config) -> None:
    transcriber = MlxWhisperTranscriber(cfg.whisper_model, cfg.whisper_language)
    report = process(db, paths, cfg, transcriber, now_ms=now_ms())
    db.set_status("last_process", json.dumps(report.to_json_dict()))
    for line in _report_lines(report):
        click.echo(line)


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
    with db:
        result = import_capture(db, paths, capture, complete=not incomplete)
        db.set_status("last_import_iso", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        click.echo(
            f"Imported {capture.name}: {result.messages} messages, "
            f"{result.pages_new} new pages, {result.pages_duplicate} duplicates"
        )
        if run_process:
            decode_new_pages(db, paths, result, capture_day=date.today())
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
def status_cmd() -> None:
    """Show what the state database holds."""
    paths, cfg, db = _setup()
    with db:
        s = status_summary(db, paths, cfg, now_ms=now_ms())
    click.echo(f"Days with clips: {len(s['days_with_clips'])}")
    click.echo(f"Pending transcripts: {s['pending_transcripts']}")
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


def _model_cache_dir(model: str) -> Path:
    return Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + model.replace("/", "--"))


@main.command("doctor")
@click.option("--download-model", is_flag=True, help="Fetch the whisper model (the only networked action).")
def doctor_cmd(download_model: bool) -> None:
    """Check the environment."""
    paths = Paths(default_root())
    paths.ensure()
    cfg = load_config(paths.config)
    if download_model:
        import huggingface_hub

        old = os.environ.pop("HF_HUB_OFFLINE", None)
        try:
            click.echo(f"Downloading {cfg.whisper_model} ...")
            huggingface_hub.snapshot_download(cfg.whisper_model)
        finally:
            if old is not None:
                os.environ["HF_HUB_OFFLINE"] = old
    ok = True

    def check(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        click.echo(f"{'ok  ' if good else 'FAIL'} {label}{': ' + detail if detail else ''}")

    v = sys.version_info
    check("python >= 3.12", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro}")
    check("ffmpeg", ffmpeg_available())
    probe = paths.root / ".write-test"
    try:
        probe.write_text("x")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    check("state root writable", writable, str(paths.root))
    check("whisper model cached", _model_cache_dir(cfg.whisper_model).exists(), cfg.whisper_model)
    if not ok:
        raise SystemExit(1)


@main.command("day")
@click.argument("day", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--open", "open_file", is_flag=True, help="Write the day file and open it.")
@click.option("--keep-noise", is_flag=True, help="Append the dropped noise clips.")
def day_cmd(day: datetime, open_file: bool, keep_noise: bool) -> None:
    """Print a day file."""
    paths, cfg, db = _setup()
    d = day.date()
    with db:
        if open_file:
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
