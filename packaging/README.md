# packaging

`Lavalier.app` is a minimal, hand-built macOS app bundle. Its only executable,
`Contents/MacOS/Lavalier`, is a small C launcher (`launcher.c`) that embeds the
Homebrew framework Python 3.12 and runs a Python module in-process. Because the
bundle's own binary is the process that talks to Bluetooth, macOS attributes the
Bluetooth grant to "Lavalier" rather than to a terminal or to "Python".

With no arguments the launcher runs `lavalier.app`. With `-m <module> [args...]`
it runs that module instead, for example `Lavalier -m lavalier.probe`.

## Build

From the repo root, with the project venv:

```
.venv/bin/python -m packaging.build_app --out dist
```

Options: `--out DIR` (default `dist`), `--identity NAME` (codesign identity,
default `-` for ad hoc), `--dry-run` (writes `Info.plist`, `PkgInfo` and
`paths.txt` but does not compile or sign). `dist/` is gitignored.

The build compiles `launcher.c` with `clang` against
`/opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12`,
linking that version's `Python` dylib directly (Homebrew's framework has no
top-level `Python` or `Versions/Current` links, so `-framework Python` cannot
find it). It then signs the bundle with
`codesign --force --deep --sign <identity> --identifier io.github.khronosd.lavalier`.

Rebuild after moving the repo or recreating the venv: the bundle refers to both
by absolute path.

## paths.txt

`Contents/Resources/paths.txt` lists the module search path, one directory per
line. The launcher reads it at startup into an isolated `PyConfig` with
`module_search_paths_set`, then appends the framework's standard library and
`lib-dynload`. Order:

1. the repo's `src` directory,
2. each site-packages directory (the running venv's `purelib`),
3. every existing directory named by a plain-path line in a `*.pth` file inside
   those site-packages directories, de-duplicated.

Step 3 exists because the isolated config never runs `site.py`, so `.pth`
files are not processed. Editable installs (`lavalier`, `pendant_client`) are
only reachable through them.

## Spike 2026-10-xx

Owner at the keyboard, pendant in range, nothing else connected.

- [ ] 1. `open dist/Lavalier.app --args -m lavalier.probe`. Expected: macOS asks
  "Lavalier would like to use Bluetooth"; allow. `~/Pendant/logs/probe.log`
  gains a line. If the prompt names "Python" instead, stop and fix the launcher.
  Outcome: ______________________________________________
- [ ] 2. Throwaway plist `/tmp/io.github.khronosd.lavalier.probe.plist` with
  `ProgramArguments` `[<abs path>/Lavalier, -m, lavalier.probe]` and `RunAtLoad`
  true; `launchctl bootstrap gui/$(id -u) /tmp/io.github.khronosd.lavalier.probe.plist`.
  Expected: no second prompt, a new line in `probe.log`. Afterwards
  `launchctl bootout gui/$(id -u)/io.github.khronosd.lavalier.probe`.
  Outcome: ______________________________________________
- [ ] 3. Rebuild (`python -m packaging.build_app --out dist`) and repeat 1.
  A: no prompt, a new line (ad hoc signature is stable enough).
  B: a prompt again, or `probe.log` shows a Bluetooth denial: create a
  self-signed code-signing certificate `Lavalier Dev` in Keychain Access, rebuild
  with `--identity "Lavalier Dev"`, repeat 1 and 3 once more. The identity that
  works becomes the default `--identity` in `build_app.py`.
  Outcome (A or B, identity): ______________________________________________
- [ ] 4. System Settings > Privacy & Security > Bluetooth shows "Lavalier" with
  the switch on.
  Outcome / screenshot path: ______________________________________________
