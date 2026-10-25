"""The window's built page ships with the package and fetches nothing from outside the app."""

import re
from pathlib import Path

import lavalier.server

DIST = Path(lavalier.server.WEB_ROOT)
REF = re.compile(r"""\b(?:src|href)\s*=\s*["']?([^"'\s>]+)""", re.IGNORECASE)


def test_index_exists_and_is_the_server_web_root():
    assert DIST == Path(lavalier.server.__file__).parent / "web" / "dist"
    assert (DIST / "index.html").is_file()


def test_index_references_only_assets_that_exist():
    text = (DIST / "index.html").read_text()
    refs = REF.findall(text)
    assert refs, "the built page loads its script and stylesheet"
    for ref in refs:
        assert ref.startswith("/assets/"), ref
        assert (DIST / ref.lstrip("/")).is_file(), ref


def test_index_names_no_remote_url():
    text = (DIST / "index.html").read_text()
    assert "http://" not in text and "https://" not in text


def test_the_insights_styles_take_their_radii_from_the_tokens():
    css = (Path(__file__).parent.parent / "web" / "src" / "styles" / "insights.css").read_text()
    radii = re.findall(r"border-radius:\s*([^;]+);", css)
    assert radii and all(r.strip().startswith("var(--radius-") for r in radii), radii
