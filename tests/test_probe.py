from fake_pendant import FakePendant

from lavalier.probe import read_status


async def test_read_status_is_read_only_and_fills_firmware():
    p = FakePendant(firmware="1.1.3", storage_instance=9)
    s = await read_status(p, now_ms=5)
    assert s.firmware_ver == "1.1.3" and s.storage_instance == 9 and s.read_at_ms == 5
    assert p.log == ["enter", "info", "status", "exit"]
