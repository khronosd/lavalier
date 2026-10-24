import pytest

from fake_pendant import FakePendant
from lavalier.device import DeviceError, snapshot_from_status


def test_snapshot_from_status_maps_enums_and_pages():
    from pendant_client.proto import server_pb2, shared_pb2
    ds = server_pb2.DeviceStatus(has_all_fields=True)
    ds.recording_status.recording_state = shared_pb2.EnumC11643f.Value("LISTENING")
    ds.storage_state.oldest_flash_page = 10; ds.storage_state.newest_flash_page = 19
    ds.battery_status.soc = 94; ds.battery_status.current = 51
    ds.battery_status.usb_state = shared_pb2.Usb.Value("USB_DISCONNECTED")
    s = snapshot_from_status(ds, read_at_ms=5, firmware_ver="1.1.3", storage_instance=3)
    assert (s.recording_state, s.pages_waiting, s.soc, s.current_ma, s.usb_state, s.firmware_ver, s.storage_instance) == ("LISTENING", 10, 94, 51, "USB_DISCONNECTED", "1.1.3", 3)


def test_partial_status_is_marked_and_not_trusted():
    from pendant_client.proto import server_pb2
    ds = server_pb2.DeviceStatus(has_all_fields=False)
    ds.storage_state.newest_flash_page = 3
    s = snapshot_from_status(ds, read_at_ms=1)
    assert s.has_all_fields is False and s.pages_waiting == 4 and s.recording_state == "NOT_RECORDING"


async def test_fake_pendant_scripts_mute_and_drain():
    p = FakePendant(messages=[b"a", b"b"], disconnect_after=None)
    async with p:
        await p.stop_recording(); assert (await p.status()).recording_state == "NOT_RECORDING"
        got = [m async for m in p.drain(idle_s=5)]
        await p.start_recording(); assert (await p.status()).recording_state == "LISTENING"
    assert got == [b"a", b"b"] and p.log[0] == "enter" and p.log[-1] == "exit"


async def test_fake_pendant_drops_the_link():
    p = FakePendant(messages=[b"a", b"b", b"c"], disconnect_after=2)
    async with p:
        with pytest.raises(DeviceError):
            [m async for m in p.drain(idle_s=5)]
