# pendant-recorder

A local macOS tool that turns captures from a BLE audio pendant into
transcripts and Markdown day files. Nothing leaves the machine unless you
configure a destination.

## Development

The decoder is the `pendant_client` package.
The editable fork checkout is the development setup for now; a git URL will
follow when it is published.

```
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]" -e /Users/khronos/Repos/pendant-cli/.worktrees/plan-01-core
.venv/bin/pytest -q
```

## License

MIT
