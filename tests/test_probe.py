from fake_pendant import FakePendant

from lavalier.probe import main, read_status


async def test_read_status_is_read_only_and_fills_firmware():
    p = FakePendant(firmware="1.1.3", storage_instance=9)
    s = await read_status(p, now_ms=5)
    assert s.firmware_ver == "1.1.3" and s.storage_instance == 9 and s.read_at_ms == 5
    assert p.log == ["enter", "info", "status", "exit"]


def test_main_logs_not_in_range_and_exits_2(tmp_path, monkeypatch):
    root = tmp_path / "Pendant"
    root.mkdir()
    (root / "config.toml").write_text('pendant_address = "UUID-1"\n')
    monkeypatch.setenv("PENDANT_ROOT", str(root))
    assert main(pendant_factory=lambda cfg: FakePendant(in_range=False)) == 2
    assert (root / "logs" / "probe.log").read_text().splitlines()[-1].endswith(" not-in-range")
