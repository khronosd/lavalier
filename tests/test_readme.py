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


def test_readme_says_what_the_range_control_shows_and_when_a_day_goes_out():
    text = (Path(__file__).parent.parent / "README.md").read_text()
    assert "the days without insights before anything is sent" not in text
    assert "how many days, roughly how many tokens and what it would cost" in text
    assert "after the first drain that follows" in text
    assert "openai@<host>" in text and "not encrypted" in text


NOTION_SENTENCE = ("Sends each day's text, and its Insights once generated, to the Notion database you choose. "
                   "Audio is never sent.")
CALENDAR_SENTENCE = ("Reads the calendars you pick on this Mac to name conversations after the event they overlap. "
                     "Nothing leaves this Mac.")


def test_readme_documents_the_connectors():
    text = (Path(__file__).parent.parent / "README.md").read_text()
    assert "## Connectors" in text and "`lavalier export" in text
    assert NOTION_SENTENCE in text and CALENDAR_SENTENCE in text
    assert "Written by lavalier. Edits inside this block are overwritten; add your notes outside it." in text
    assert "Export again" in text and "stopped" in text and "Limitless" not in text
    assert "dedicated database" in text


def test_bundle_readme_notes_eventkit_and_the_calendar_prompt():
    text = (Path(__file__).parent.parent / "bundle" / "README.md").read_text()
    assert "pyobjc-framework-EventKit" in text and "notion-client" in text
    assert "NSCalendarsFullAccessUsageDescription" in text and "Limitless" not in text
