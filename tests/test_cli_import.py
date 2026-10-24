from click.testing import CliRunner

from lavalier.cli import main


def test_cli_import_prints_summary(root, capture_file, monkeypatch):
    monkeypatch.setenv("PENDANT_ROOT", str(root.root))
    out = CliRunner().invoke(main, ["import", str(capture_file)]).output
    assert "3 new pages, 0 duplicates" in out
