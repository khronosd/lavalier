from pathlib import Path


def test_readme_documents_every_command_and_the_lock():
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    for cmd in ("sync", "status --live", "mute", "unmute", "install-agent", "uninstall-agent", "app"):
        assert f"`{cmd}" in text, cmd
    assert "~/Pendant/.lock" in text and "30 minutes" in text and "Limitless" not in text


def test_readme_documents_the_window():
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "## The window" in text and "`window`" in text and "Limitless" not in text
