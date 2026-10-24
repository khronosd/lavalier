# pendant-recorder

A local macOS tool that turns captures from a BLE audio pendant into
transcripts and Markdown day files. It decodes the audio, drops noise clips,
transcribes speech with a local Whisper model, groups clips into conversations
and writes one Markdown file per day.

Audio never leaves this Mac. This version makes no network connection at all except `doctor --download-model`.

## Install

Requires macOS on Apple Silicon, Python 3.12 and ffmpeg.

The decoder is the `pendant_client` package. The editable fork checkout is the
development setup for now; a git URL will follow when it is published.

```
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]" -e /Users/khronos/Repos/pendant-cli/.worktrees/plan-01-core
.venv/bin/pytest -q
```

## First run

```
.venv/bin/pendant-recorder doctor --download-model
.venv/bin/pendant-recorder import <capture.bin> --process
.venv/bin/pendant-recorder day <YYYY-MM-DD>
```

`doctor --download-model` is the only step that touches the network; run it
once to fetch the speech model.

## Commands

- `doctor [--download-model]`: check Python, ffmpeg, the state root and the cached model (exits 1 if a check fails); optionally fetch the model.
- `status`: print days with clips, pending transcripts, audio and capture bytes on disk, next deletion, last import, pinned conversations, button-press counts and the last process report.
- `import <bin> [--incomplete] [--process]`: import a capture file; `--incomplete` accepts a partial capture, `--process` runs the pipeline after.
- `process`: decode, transcribe, group and write day files for anything pending.
- `day <YYYY-MM-DD> [--open] [--keep-noise]`: print that day's Markdown; `--open` writes the file and opens it; `--keep-noise` appends dropped noise clips (print mode only).
- `pin <conversation-id>` / `unpin <conversation-id>`: keep that conversation's audio for good, or release it.
- `retention --now`: apply the retention policy immediately (`--now` is required).

## State root

Everything lives under `~/Pendant/`, or `$PENDANT_ROOT` if set:

```
config.toml     settings (see src/pendant_recorder/config.py)
state.sqlite    clips, captures, transcripts, pins
captures/       imported capture files
audio/<date>/   decoded audio clips
days/           the Markdown day files
logs/
```

## Retention

Audio is deleted after 14 days by default; transcripts and day files stay.
Starred, pinned and failed clips are kept.

## Tests

`.venv/bin/pytest -q` runs the suite. The fixture test for the 2026-10-23
capture skips when the capture file is absent and otherwise runs in about 30 s.
A separate test runs the whole pipeline with sockets blocked.

## License

MIT
