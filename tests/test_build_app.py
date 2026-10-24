import importlib.util
import plistlib
from pathlib import Path

# The repo's top-level `packaging/` directory shares its name with the PyPI `packaging`
# library, which pytest has already imported, so load build_app by path.
_spec = importlib.util.spec_from_file_location(
    "lavalier_build_app", Path(__file__).resolve().parents[1] / "packaging" / "build_app.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
info_plist = _mod.info_plist
build = _mod.build


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
