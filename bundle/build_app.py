"""Build Lavalier.app by hand: Info.plist, an embedding launcher, search paths, ad hoc signature.

    python -m bundle.build_app [--out dist] [--identity -] [--dry-run]
"""

import argparse
import plistlib
import subprocess
import sysconfig
from pathlib import Path

BUNDLE_ID = "io.github.khronosd.lavalier"
VERSION = "0.2.0"
PYTHON_FRAMEWORK = Path("/opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def info_plist(*, version: str, ui_element: bool = True) -> dict:
    return {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": "Lavalier",
        "CFBundleDisplayName": "Lavalier",
        "CFBundleExecutable": "Lavalier",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": version,
        "CFBundleShortVersionString": version,
        "LSMinimumSystemVersion": "14.0",
        "LSUIElement": ui_element,
        "NSHighResolutionCapable": True,
        "NSBluetoothAlwaysUsageDescription": (
            "Lavalier connects to your pendant to read its status and download its recordings."
        ),
    }


def _pth_dirs(site_dir: Path) -> list[Path]:
    """Directories named by plain-path lines in site_dir/*.pth.

    The launcher's isolated config never runs site.py, so editable installs listed in .pth
    files must be spelled out in paths.txt. Import lines and missing directories are skipped.
    """
    out: list[Path] = []
    if not site_dir.is_dir():
        return out
    for pth in sorted(site_dir.glob("*.pth")):
        for raw in pth.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(("import ", "import\t")):
                continue
            d = Path(line) if Path(line).is_absolute() else site_dir / line
            if d.is_dir():
                out.append(d)
    return out


def search_paths(src_dir: Path, site_packages: list[Path]) -> list[str]:
    ordered = [src_dir, *site_packages]
    for sp in site_packages:
        ordered.extend(_pth_dirs(sp))
    seen: set[str] = set()
    result: list[str] = []
    for p in ordered:
        s = str(p)
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def build(out_dir: Path, *, python_framework: Path, site_packages: list[Path], src_dir: Path,
          codesign_identity: str = "-", dry_run: bool = False) -> Path:
    app = out_dir / "Lavalier.app"
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps(info_plist(version=VERSION)))
    (contents / "PkgInfo").write_bytes(b"APPL????")
    (resources / "paths.txt").write_text("".join(f"{p}\n" for p in search_paths(src_dir, site_packages)))
    if dry_run:
        return app
    fw = python_framework
    exe = macos / "Lavalier"
    # Homebrew's Python.framework has no top-level `Python` or `Versions/Current` links, so
    # `-F... -framework Python` cannot resolve it. Link the versioned dylib directly; its
    # install name is absolute, so no rpath is needed.
    subprocess.run(
        [
            "clang", "-O2", "-o", str(exe), str(HERE / "launcher.c"),
            f"-I{fw}/include/python3.12",
            str(fw / "Python"),
            f'-DPY_HOME="{fw}"',
            f'-DPY_STDLIB="{fw}/lib/python3.12"',
        ],
        check=True,
    )
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", codesign_identity, "--identifier", BUNDLE_ID, str(app)],
        check=True,
    )
    return app


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bundle.build_app", description="Build Lavalier.app")
    ap.add_argument("--out", type=Path, default=Path("dist"))
    ap.add_argument("--identity", default="-", help='codesign identity ("-" for ad hoc)')
    ap.add_argument("--dry-run", action="store_true", help="lay out the bundle without compiling or signing")
    args = ap.parse_args(argv)
    app = build(
        args.out,
        python_framework=PYTHON_FRAMEWORK,
        site_packages=[Path(sysconfig.get_paths()["purelib"])],
        src_dir=REPO / "src",
        codesign_identity=args.identity,
        dry_run=args.dry_run,
    )
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
