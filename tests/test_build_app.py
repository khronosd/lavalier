import plistlib
import subprocess
from pathlib import Path

from bundle.build_app import build, default_identity, info_plist


def test_info_plist_has_the_bluetooth_description_and_identity():
    p = info_plist(version="0.2.0")
    assert p["CFBundleIdentifier"] == "io.github.khronosd.lavalier"
    assert p["CFBundleExecutable"] == "Lavalier" and p["LSUIElement"] is True
    assert p["NSBluetoothAlwaysUsageDescription"].startswith("Lavalier connects to your pendant")
    assert "Limitless" not in plistlib.dumps(p).decode()


def test_dry_run_lays_out_the_bundle_without_compiling(tmp_path):
    app = build(tmp_path, python_framework=Path("/fw/3.12"), site_packages=[Path("/sp")], src_dir=Path("/src"), dry_run=True)
    assert (app / "Contents/Info.plist").exists() and (app / "Contents/PkgInfo").read_bytes() == b"APPL????"
    assert (app / "Contents/Resources/paths.txt").read_text().splitlines() == ["/src", "/sp"]
    assert not (app / "Contents/MacOS/Lavalier").exists()


def _canned(stdout):
    def run(cmd, **kwargs):
        assert cmd == ["security", "find-identity", "-v", "-p", "codesigning"]
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return run


def test_default_identity_prefers_lavalier_dev():
    out = '  1) 34476D23AB12CD34EF56AB78CD90EF12AB34CD56 "Lavalier Dev"\n     1 valid identities found\n'
    assert default_identity(run=_canned(out)) == "Lavalier Dev"


def test_default_identity_falls_back_to_ad_hoc():
    assert default_identity(run=_canned("     0 valid identities found\n")) == "-"


CALENDAR_SENTENCE = ("Lavalier reads your calendars to name conversations after the event they overlap. "
                     "Nothing leaves this Mac.")


def test_the_dry_run_plist_carries_the_calendar_usage_descriptions(tmp_path):
    app = build(tmp_path, python_framework=Path("/fw/3.12"), site_packages=[Path("/sp")], src_dir=Path("/src"), dry_run=True)
    p = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert p["NSCalendarsFullAccessUsageDescription"] == CALENDAR_SENTENCE
    assert p["NSCalendarsUsageDescription"] == CALENDAR_SENTENCE
