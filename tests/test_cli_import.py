from click.testing import CliRunner

from lavalier.cli import main


def test_cli_import_prints_summary(root, capture_file, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    out = CliRunner().invoke(main, ["import", str(capture_file)]).output
    assert "3 new pages, 0 duplicates" in out


def test_cli_import_orphans_reports_each(root, capture_file, monkeypatch):
    import os
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    root.ensure()
    orphan = root.captures / "20261024T055640Z.bin"
    orphan.write_bytes(capture_file.read_bytes())
    os.utime(orphan, (0, 1_792_800_000))
    r = CliRunner().invoke(main, ["import", "--orphans"])
    assert r.exit_code == 0, r.output
    assert "Imported orphan 20261024T055640Z.bin: 3 messages, 3 new pages, 0 duplicates" in r.output
    assert not orphan.exists()
    assert "No orphan captures" in CliRunner().invoke(main, ["import", "--orphans"]).output


def test_cli_import_needs_a_capture_or_orphans(root, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    r = CliRunner().invoke(main, ["import"])
    assert r.exit_code == 2 and "--orphans" in r.output
