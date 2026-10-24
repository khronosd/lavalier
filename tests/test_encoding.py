"""Every text file the app reads or writes names UTF-8: under launchd there is no locale, and the
bundled Python would otherwise fall back to ASCII (the day file's ★ once failed to write)."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "lavalier"
_TEXT_CALL = re.compile(r"\.(read_text|write_text)\(|(?<![\w.])(open|os\.fdopen)\(|subprocess\.run\(")
_BINARY = re.compile(r"""['"][rwa]\+?b['"]""")


def _calls(text: str):
    for m in _TEXT_CALL.finditer(text):
        start = m.start()
        depth, i = 0, m.end() - 1
        while i < len(text):  # the call's argument list, across lines
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield text[start:i + 1], text.count("\n", 0, start) + 1


def test_every_text_file_io_names_utf8():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        for call, line in _calls(path.read_text(encoding="utf-8")):
            if _BINARY.search(call):
                continue
            if call.startswith("subprocess.run(") and "text=True" not in call and "universal_newlines" not in call:
                continue  # bytes mode
            if "encoding=" not in call:
                offenders.append(f"{path.relative_to(SRC.parent)}:{line}: {call.splitlines()[0]}")
    assert offenders == []
