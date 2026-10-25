from pathlib import Path


def test_readme_documents_every_command_and_the_lock():
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    for cmd in ("sync", "status --live", "mute", "unmute", "install-agent", "uninstall-agent", "app"):
        assert f"`{cmd}" in text, cmd
    assert "~/Pendant/.lock" in text and "30 minutes" in text and "Limitless" not in text


def test_readme_documents_the_window():
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "## The window" in text and "`window`" in text and "Limitless" not in text


def test_readme_documents_insights():
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "## Insights" in text and "`insights" in text and "`ask" in text
    assert "io.github.khronosd.lavalier" in text and "Audio is never sent." in text and "Limitless" not in text


def test_bundle_readme_notes_the_sdks_and_the_keychain_prompt():
    text = (Path(__file__).resolve().parents[1] / "bundle" / "README.md").read_text()
    assert "keyring" in text and "Keychain" in text and "Limitless" not in text
