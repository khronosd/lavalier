import plistlib
import subprocess
import sys
from pathlib import Path

from lavalier.agent import LABEL, default_program, install, plist_dict, uninstall, AGENT_PATH
from lavalier.config import Config


def test_plist_matches_golden(tmp_path):
    d = plist_dict(program=["/Users/k/Applications/Lavalier.app/Contents/MacOS/Lavalier"],
                   log_dir=Path("/Users/k/Pendant/logs"), env={})
    assert plistlib.dumps(d, sort_keys=True) == (Path(__file__).parent / "golden" / "launch-agent.plist").read_bytes()


def test_plist_carries_pendant_root_only_when_set():
    d = plist_dict(program=["x"], log_dir=Path("/l"), env={"PENDANT_ROOT": "/r"})
    assert d["EnvironmentVariables"]["PENDANT_ROOT"] == "/r"
    assert "PENDANT_ROOT" not in plist_dict(program=["x"], log_dir=Path("/l"), env={})["EnvironmentVariables"]


def test_default_program_prefers_the_bundle(tmp_path):
    cfg = Config()
    assert default_program(cfg, bundle_default=tmp_path / "none.app") == [sys.executable, "-m", "lavalier.app"]
    (tmp_path / "Lavalier.app/Contents/MacOS").mkdir(parents=True)
    (tmp_path / "Lavalier.app/Contents/MacOS/Lavalier").touch()
    assert default_program(cfg, bundle_default=tmp_path / "Lavalier.app") == [str(tmp_path / "Lavalier.app/Contents/MacOS/Lavalier")]


def test_default_program_uses_the_configured_bundle(tmp_path):
    (tmp_path / "My.app/Contents/MacOS").mkdir(parents=True)
    (tmp_path / "My.app/Contents/MacOS/Lavalier").touch()
    got = default_program(Config(app_bundle=str(tmp_path / "My.app")), bundle_default=tmp_path / "none.app")
    assert got == [str(tmp_path / "My.app/Contents/MacOS/Lavalier")]


def test_install_writes_plist_and_bootstraps(root, tmp_path):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    p = install(root, Config(), run=run, agents_dir=tmp_path)
    assert p.name == f"{LABEL}.plist" and p.parent == tmp_path
    assert calls[0][:2] == ["launchctl", "bootout"]
    assert calls[-1][:2] == ["launchctl", "bootstrap"] and calls[-1][-1] == str(p)
    assert plistlib.loads(p.read_bytes())["StandardOutPath"] == str(root.logs / "app.out.log")


def test_uninstall_is_idempotent(tmp_path):
    run = lambda *a, **k: subprocess.CompletedProcess(a, 0)  # noqa: E731
    assert uninstall(run=run, agents_dir=tmp_path) is False
    (tmp_path / f"{LABEL}.plist").write_bytes(b"x")
    assert uninstall(run=run, agents_dir=tmp_path) is True
    assert not (tmp_path / f"{LABEL}.plist").exists()


def test_plist_sets_utf8_mode(tmp_path):
    d = plist_dict(program=["/x"], log_dir=tmp_path, env={})
    assert d["EnvironmentVariables"]["PYTHONUTF8"] == "1"


def test_plist_keeps_the_root_beside_utf8_mode(tmp_path):
    d = plist_dict(program=["/x"], log_dir=tmp_path, env={"PENDANT_ROOT": "/r"})
    assert d["EnvironmentVariables"] == {"PATH": AGENT_PATH, "PENDANT_ROOT": "/r", "PYTHONUTF8": "1"}


def test_plist_gives_the_agent_a_path_with_homebrew():
    """launchd's default PATH has no /opt/homebrew/bin, where ffmpeg lives."""
    d = plist_dict(program=["x"], log_dir=Path("/l"), env={})
    assert d["EnvironmentVariables"]["PATH"] == "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
