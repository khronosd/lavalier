import plistlib
from pathlib import Path

from bundle.build_app import build, info_plist


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
