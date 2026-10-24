# bundle

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
.venv/bin/python -m bundle.build_app --out dist
```

Options: `--out DIR` (default `dist`), `--identity NAME` (codesign identity;
default "Lavalier Dev" when `security find-identity -v -p codesigning` lists it,
else `-` for ad hoc, with a warning that the Bluetooth grant will not survive a
rebuild), `--dry-run` (writes `Info.plist`, `PkgInfo` and
`paths.txt` but does not compile or sign). `dist/` is gitignored.

The build compiles `launcher.c` with `clang` against
`/opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12`,
linking that version's `Python` dylib directly (Homebrew's framework has no
top-level `Python` or `Versions/Current` links, so `-framework Python` cannot
find it). It then signs the bundle with
`codesign --force --deep --sign <identity> --identifier io.github.khronosd.lavalier`.

The bundle must be rebuilt if the repo, the venv or the Python framework moves: it refers to
all three by absolute path.

## paths.txt

`Contents/Resources/paths.txt` lists the module search path, one directory per
line. The launcher reads it at startup into an isolated `PyConfig` with
`module_search_paths_set`, then appends the framework's standard library and
`lib-dynload`. Order:

1. the repo's `src` directory,
2. each site-packages directory (the running venv's `purelib`),
3. every existing directory named by a plain-path line in a `*.pth` file inside
   those site-packages directories, de-duplicated.

Step 3 exists because the launcher sets `site_import = 0`, so `site.py` never
runs and `.pth` files are not processed (nor is any global site-packages added). Editable installs (`lavalier`, `pendant_client`) are
only reachable through them.

## Signing identity

An ad hoc signature changes with every changed binary, and macOS ties the
Bluetooth grant to the signature, so each rebuild would prompt again. A
self-signed certificate gives a stable designated requirement
(`identifier "io.github.khronosd.lavalier" and certificate leaf = H"..."`).
On a new machine:

1. Keychain Access > Certificate Assistant > Create a Certificate: name
   `Lavalier Dev`, Identity Type "Self Signed Root", Certificate Type
   "Code Signing".
2. Trust it for code signing (until then `security find-identity -v` lists
   0 valid identities):
   ```
   security find-certificate -c "Lavalier Dev" -p > cert.pem
   security add-trusted-cert -r trustRoot -p codeSign -k ~/Library/Keychains/login.keychain-db cert.pem
   ```
3. Check: `security find-identity -v -p codesigning` lists `"Lavalier Dev"`.
   `build_app` then uses it by default.

## Spike 2026-10-24

Owner at the keyboard, pendant in range, nothing else connected.

- [x] 1. `open dist/Lavalier.app --args -m lavalier.probe`. Expected: macOS asks
  "Lavalier would like to use Bluetooth"; allow. `~/Pendant/logs/probe.log`
  gains a line. If the prompt names "Python" instead, stop and fix the launcher.
  Outcome: the prompt named "Lavalier"; allowed. `probe.log` lines at 09:16:11
  and 09:16:29 (state NOT_RECORDING, pages 981/982, soc 100%, firmware 1.1.3
  a9c86b051fb6).
- [x] 2. Throwaway plist `/tmp/io.github.khronosd.lavalier.probe.plist` with
  `ProgramArguments` `[<abs path>/Lavalier, -m, lavalier.probe]` and `RunAtLoad`
  true; `launchctl bootstrap gui/$(id -u) /tmp/io.github.khronosd.lavalier.probe.plist`.
  Expected: no second prompt, a new line in `probe.log`. Afterwards
  `launchctl bootout gui/$(id -u)/io.github.khronosd.lavalier.probe`.
  Outcome: the launchd-started probe wrote a line at 09:45:50 with no prompt;
  the agent was booted out. Side note: the BLE transport logs "Bleak backend
  doesn't expose .pair()" to stderr on each connect; harmless.
- [x] 3. Rebuild (`python -m bundle.build_app --out dist`) and repeat 1.
  A: no prompt, a new line (ad hoc signature is stable enough).
  B: a prompt again, or `probe.log` shows a Bluetooth denial: create a
  self-signed code-signing certificate `Lavalier Dev` in Keychain Access, rebuild
  with `--identity "Lavalier Dev"`, repeat 1 and 3 once more. The identity that
  works becomes the default `--identity` in `build_app.py`.
  Outcome: B. A byte-identical rebuild kept the same CDHash and proved nothing,
  so the bundle was changed (version bump, ad hoc re-sign, new CDHash) and the
  prompt came back at 09:47. The "Lavalier Dev" certificate was created and
  trusted as in "Signing identity" above. Rebuilt with
  `--identity "Lavalier Dev"`: the designated requirement became
  `identifier "io.github.khronosd.lavalier" and certificate leaf = H"34476d23…"`.
  The first run prompted once (09:51:48); a further changed binary re-signed
  with the same identity ran with no prompt (09:52:23). "Lavalier Dev" is now
  the default identity.
- [x] 4. System Settings > Privacy & Security > Bluetooth shows "Lavalier" with
  the switch on.
  Outcome: the list shows "Lavalier" once, switched on.

## What the bundle runs

The bundle runs whatever the checkout and the venv hold at its next restart: it
does not carry a copy of the code. Switch branches with the agent stopped, or
rebuild and restart it afterwards, so the running app never changes under itself.
