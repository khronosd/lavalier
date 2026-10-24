import plistlib

from fake_pendant import FakePendant
from lavalier import cli, doctor
from lavalier.config import Config
from lavalier.device import DeviceError
from lavalier.doctor import bluetooth_check, competing_agents


def test_competing_agents_found_by_label_or_program(tmp_path):
    (tmp_path / "Limitless.plist").write_bytes(plistlib.dumps({"Label": "Limitless", "ProgramArguments": ["/Applications/Limitless.app/Contents/MacOS/Limitless"], "RunAtLoad": True}))
    (tmp_path / "com.example.other.plist").write_bytes(plistlib.dumps({"Label": "com.example.other", "ProgramArguments": ["/usr/bin/true"]}))
    assert competing_agents(tmp_path) == ["Limitless"]


def test_competing_agent_found_by_program_alone(tmp_path):
    (tmp_path / "x.plist").write_bytes(plistlib.dumps({"Label": "com.x.helper", "ProgramArguments": ["/Applications/Limitless.app/helper"]}))
    (tmp_path / "broken.plist").write_text("not a plist")
    assert competing_agents(tmp_path) == ["com.x.helper"]


def test_competing_agents_missing_dir(tmp_path):
    assert competing_agents(tmp_path / "nope") == []


def test_doctor_warns_about_a_competing_agent_but_passes(cli_env, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "LAUNCH_AGENTS_DIR", tmp_path)
    (tmp_path / "Limitless.plist").write_bytes(plistlib.dumps({"Label": "Limitless", "ProgramArguments": ["/x"]}))
    r = cli_env.invoke(["doctor", "--no-device"])
    assert r.exit_code == 0 and "WARN another launch agent syncs this pendant: Limitless" in r.output
    assert "Limitless.plist" in r.output and "unload it before the first drain" in r.output
    assert "pendant reachable" not in r.output


def test_doctor_reaches_the_pendant_read_only(cli_env, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "LAUNCH_AGENTS_DIR", tmp_path)
    p = FakePendant(pages=(0, 786))
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: p)
    r = cli_env.invoke(["doctor"])
    assert "ok   pendant reachable: LISTENING, 787 pages, fw 1.1.3" in r.output and "stop" not in p.log and "set_time" not in " ".join(p.log)
    assert r.exit_code == 0


def test_bluetooth_check_outcomes():
    cfg = Config(pendant_address="FAKE")
    assert bluetooth_check(cfg, lambda c: FakePendant(in_range=False)) == (True, "not in range")
    assert bluetooth_check(cfg, lambda c: FakePendant(fail_on={"info": DeviceError("timeout")})) == (False, "timeout")
    assert bluetooth_check(Config(), lambda c: FakePendant())[0] is True


def test_doctor_fails_when_the_pendant_errors(cli_env, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "LAUNCH_AGENTS_DIR", tmp_path)
    monkeypatch.setattr(cli, "pendant_factory", lambda cfg: FakePendant(fail_on={"info": DeviceError("timeout")}))
    r = cli_env.invoke(["doctor"])
    assert r.exit_code == 1 and "FAIL pendant reachable: timeout" in r.output
