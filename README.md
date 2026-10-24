# lavalier

A local macOS tool that turns captures from a BLE audio pendant into
transcripts and Markdown day files. It decodes the audio, drops noise clips,
transcribes speech with a local Whisper model, groups clips into conversations
and writes one Markdown file per day.

Audio never leaves this Mac. This version makes no network connection at all except `doctor --download-model`.

## The device

The project talks to the pendant over the pendant's own BLE protocol. It does
not modify the device or its firmware and does not alter the LED.

Consent: the pendant's LED shows when it is recording, and that LED stays
under the pendant's own control. Tell the people around you that you are
recording, and follow the recording-consent law where you are.

## Install

Requires macOS on Apple Silicon, Python 3.12 and ffmpeg.

The decoder is the `pendant_client` package from the `pendant-cli` fork. For
development, check it out next to this repository and install it editable; a
git URL will follow when it is published.

```
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]" -e ../pendant-cli
.venv/bin/pytest -q
```

## First run

```
.venv/bin/lavalier doctor --download-model
.venv/bin/lavalier import <capture.bin> --process
.venv/bin/lavalier day <YYYY-MM-DD>
```

`doctor --download-model` is the only step that touches the network; run it
once to fetch the speech model.

## Commands

- `doctor [--download-model] [--no-device]`: check Python, ffmpeg, the state root, the cached model and, if `pendant_address` is set, a read-only status read of the pendant (exits 1 if a check fails); `--download-model` fetches the model, `--no-device` skips the pendant. It also warns about another launch agent that syncs the pendant.
- `sync [--dry-run]`: drain the pendant now, then process what came in. Through the app, the drain's result comes back at once and processing runs on in the app (`status` shows it when done). `--dry-run` connects, reads and decides, and changes nothing on the pendant.
- `status [--live]`: print days with clips, pending transcripts, failed clips, audio and capture bytes on disk, next deletion, last import, pinned conversations, button-press counts, the last process report, the last pendant status, who muted the pendant ("muted by the recorder" or "muted by you") and the last sync. `--live` reads the pendant first (read-only; it does not set the clock).
- `mute` / `unmute`: set the pendant's clock, then stop or restart recording. `mute` is the owner's mute and sync leaves it alone; `unmute` also clears every mute marker the recorder holds.
- `app`: run the background app in the foreground (scheduler plus the loopback control server).
- `window`: open the window on the running background app (see "The window").
- `install-agent [--program ...]` / `uninstall-agent`: install or remove the launch agent that keeps the app running from login. `--program` replaces the program argv; repeat it once per argument.
- `import [<bin>] [--incomplete] [--orphans] [--process]`: import a capture file; `--incomplete` accepts a partial capture; `--orphans` imports any capture a cancelled or killed drain left in `captures/` without importing it (each sync also does this before it connects); `--process` runs the pipeline after.
- `process`: measure loudness, transcribe, group and write day files for anything pending. Without ffmpeg or the cached model it skips those stages and leaves clips pending.
- `day <YYYY-MM-DD> [--open] [--keep-noise]`: print that day's Markdown; `--open` writes the file and opens it; `--keep-noise` appends dropped noise clips (print mode only).
- `pin <conversation-id>` / `unpin <conversation-id>`: keep that conversation's audio for good, or release it.
- `retry-failed`: put failed clips back in the queue; the next `process` retries them.
- `retention --now`: apply the retention policy immediately (`--now` is required).

`sync`, `status --live`, `mute` and `unmute` need `pendant_address` in `config.toml`. When the background app is running, they go through it. `sync --dry-run` and `doctor` run in the CLI under the same lock, and skip or refuse when the app holds the pendant. The lock is what guarantees one Bluetooth link at a time.

## How syncing works

A sync is one visit to the pendant. The background app makes one every
`poll_interval_s` (600 s by default); `sync` makes one on demand. Each step
below happens in this order, and no device command is ever retried.

1. Take the lock (see "The lock file"). If another device user is active, the
   sync ends as `locked`. Then import any capture an earlier drain left in
   `captures/` without importing it (a drain cancelled by Ctrl-C or a stop, or
   a process killed mid-drain): the pendant already deleted those pages, so
   that file is their only copy.
2. Connect. If the pendant is not advertising, the sync ends as `not-in-range`.
3. Set the pendant's clock, read its firmware and storage instance, and read
   its status. If `require_firmware` is set and does not match, the sync ends
   as `refused`.
4. If an earlier sync left an unmute pending, or left its mute marker behind
   because its process died between the mute and the restore, and the pendant
   is not recording, send start recording once and read the status back.
5. Decide whether to drain. There are three triggers; any one is enough:
   - the pendant is on its charger (inferred from its USB serial device, a
     positive battery current, or two quiet polls in a row);
   - `drain_pages_threshold` pages are waiting (1000 by default);
   - the last good drain was more than `drain_after_hours` ago (24 by default).

   If none applies, the sync ends as `skipped`. `--dry-run` stops here and
   reports `dry-run`.
6. Mute. If the pendant is recording, the recorder sends stop recording and
   reads the status back. It drains only once the mute is confirmed. If the
   pendant was already not recording, the recorder takes that as the owner's
   mute, drains, and leaves it muted, unless its own unmute is still pending:
   then the mute is reported as the recorder's, the drain goes ahead, and the
   restore sends nothing (the pending unmute keeps the 30-minute rule below). If the status read was partial, it
   drains without muting and says so in the reason.
7. Drain: download the pages into a capture file, writing a heartbeat to the
   lock every 100 messages. The download acknowledges each page by deleting it
   from the pendant.
8. Import the capture and decode it. A drain cut short by a dropped link still
   imports what arrived and is marked incomplete.
9. Restore. If the recorder muted the pendant, it marks the unmute as pending,
   sends start recording once and reads the status back. A confirmed state
   clears the marker.
10. Process the new clips (loudness, transcription, grouping, day files).

Any unexpected failure ends the sync as `error` with the message. Check the
LED and the log before running it again. A sync cancelled mid-way (Ctrl-C, or
the app stopping) still restores the pendant, and ends as `error` with the
message `cancelled`; what it drained is imported by the next sync.

### The 30-minute rule

If the recorder's unmute was not confirmed (the link dropped, or the status did
not show recording), it marks the unmute as pending. The marker is set at the
restore step, after the drain, so a long drain moves the start of the window.

If the recorder's process died after muting and before restoring (a crash, a
forced quit, power loss), only its mute marker is left. The next sync that
finds the pendant not recording takes that as the recorder's mute and marks the
unmute pending from the time of the mute itself.

On every later sync (not `--dry-run`), within 30 minutes of that marker, the
recorder retries while the pendant reports NOT_RECORDING with a complete
status. It sends start recording at most once per sync and reads the status
back. After 30 minutes it stops retrying, adds "unmute pending since <time>" to
the sync's reason, and leaves the marker for you. `status` shows it as
"Pendant muted by the recorder, unmute pending since <time>: run 'lavalier
unmute' or hold the button" (or "Pendant muted by the recorder since <time>"
while only the mute marker is set). Either one clears it. A pendant seen
listening or recording clears the marker by itself, instead of a retry. After
your own `mute`, `status` says "Pendant muted by you since <time>" while the
last full status read shows it not recording.

### What the recorder sends to the pendant

The set is closed: device info, device status, set clock, stop recording,
start recording, download pages and delete page (the acknowledgement inside the
download). Nothing else is ever sent, and a test enforces it.

## State root

Everything lives under `~/Pendant/`, or `$PENDANT_ROOT` if set:

```
config.toml     settings (see src/lavalier/config.py)
state.sqlite    clips, captures, transcripts, pins
.lock           the device lock (see "The lock file")
.server.json    port, token and PID of the running app
captures/       imported capture files
audio/<date>/   decoded audio clips
days/           the Markdown day files
logs/           app.log, app.out.log, app.err.log
```

## Background app

`lavalier app` runs the scheduler and a control server bound to 127.0.0.1. The
server writes its port, a random token and its PID to `~/Pendant/.server.json`
(mode 0600). The CLI reads that file to hand work to the running app.

`install-agent` writes `~/Library/LaunchAgents/io.github.khronosd.lavalier.plist`
and loads it, so the app starts at login and is restarted if it exits. The
program is the bundle named by the `app_bundle` setting, else
`~/Applications/Lavalier.app`, whichever exists first in that order, else this Python with `-m lavalier.app`. The bundle matters because
macOS gives the Bluetooth permission to the app that holds the link; see
"Building the app bundle".

Logs are in `~/Pendant/logs/`: `app.log` (rotates at 5 MB, three backups) has
the app's own lines; `app.out.log` and `app.err.log` capture the launch agent's
stdout and stderr.

To stop the app, run `uninstall-agent`; it unloads the agent and removes the
plist. A plain `launchctl bootout gui/$(id -u)/io.github.khronosd.lavalier`
stops it until the next login. If you started `lavalier app` yourself, press
Ctrl-C; the app finishes restoring the pendant before it exits. A drain cut
short this way keeps what it wrote in `captures/`, and the next sync imports
it (or run `lavalier import --orphans`).

If the program is bare Python because no bundle was found, `install-agent`
warns: that process has no Bluetooth grant, so every poll reads
`not-in-range`. Build the bundle and run `install-agent` again.

## The lock file

Only one process may talk to the pendant at a time. The recorder holds
`~/Pendant/.lock` (under the state root) from before it connects until after it
disconnects.

- Line 1 is the PID of the holder.
- Line 2 is the last heartbeat in Unix milliseconds. The holder rewrites it
  every 100 messages during a drain.
- The lock is stale after 30 minutes without a heartbeat, or when the PID is
  dead. A stale lock is taken over.

Any other tool that talks to the pendant should check this file, and `ps` for
`lavalier`, before it connects. If the lock is present and live, do not
connect. The recorder does the same in reverse: it refuses to connect while a
`pendant`, `pendant_client`, `smpmgr` or `smp_probe` process, or the pendant
maker's desktop app, is running, and reports the sync as `locked`.

## Another app syncing the pendant

Two apps draining one pendant take each other's pages and leave both with
gaps. `doctor` looks in `~/Library/LaunchAgents` for the pendant maker's
desktop app and its launch agent. If it finds one it prints a line like
`WARN another launch agent syncs this pendant: <label> (<plist path>)`. Unload
it before the first drain:

```
launchctl bootout gui/$(id -u)/<label>
mv <plist path> ~/Documents/    # anywhere outside ~/Library/LaunchAgents
```

`bootout` stops it for this login; moving the plist stops it from coming back
at the next one. Quit the desktop app too, or it may reconnect when opened.

## Retention

Audio is deleted after 14 days by default; transcripts and day files stay.
Starred, pinned and failed clips are kept.

## The window

`lavalier window` opens a native window on the background app. It shows the
Journal (days and conversations), the Transcript for a conversation, Search,
Starred clips, Audio, and the pendant card (its state and the last sync).

- It needs the background app. If the app is not running it prints how to start
  it and exits 1; it never starts one itself.
- It is a separate process from the app. A webview crash then closes only the
  window; the recorder keeps running.
- Appearance (System, Light or Dark) is a setting in the window and
  is stored in `config.toml`.
- Audio plays only while the clip is within retention; the transcript stays
  after the audio is deleted.
- Search covers every day, not only the one on screen.
- The window's size is remembered: it is saved to `config.toml` when you close it.

## Building the app bundle

`Lavalier.app` is a small hand-built bundle whose launcher embeds Python, so
macOS attributes the Bluetooth permission to "Lavalier". Build and signing
steps, and the permission spike, are in [bundle/README.md](bundle/README.md).

## Known limitations

- A conversation that crosses midnight appears in both day files, split at
  midnight: clips are grouped per day.

## Tests

`.venv/bin/pytest -q` runs the suite. The fixture test for the 2026-10-23
capture skips when the capture file is absent and otherwise runs in about 30 s.
A separate test runs the whole pipeline with sockets blocked.

## License

MIT
