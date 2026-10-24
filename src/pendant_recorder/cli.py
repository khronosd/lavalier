"""Command-line entry point."""

from pathlib import Path

import click

from pendant_recorder.db import Database
from pendant_recorder.pages import import_capture
from pendant_recorder.paths import Paths, default_root


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Turn pendant captures into transcripts and day files."""


@main.command("import")
@click.argument("capture", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--incomplete", is_flag=True, help="Mark the capture as incomplete (the link dropped).")
def import_cmd(capture: Path, incomplete: bool) -> None:
    """Register a capture .bin and record its pages."""
    paths = Paths(default_root())
    paths.ensure()
    with Database(paths.db) as db:
        db.migrate()
        result = import_capture(db, paths, capture, complete=not incomplete)
    click.echo(
        f"Imported {capture.name}: {result.messages} messages, "
        f"{result.pages_new} new pages, {result.pages_duplicate} duplicates"
    )
