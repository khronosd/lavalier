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


# --- BlePendant adapter, with the scanner and the fork session replaced ---

class _Scanner:
    found = object()

    @staticmethod
    async def find_device_by_address(address, timeout):
        return _Scanner.found


def _patch(monkeypatch, session_cls, found=True):
    from lavalier import device
    _Scanner.found = object() if found else None
    monkeypatch.setattr(device, "BleakScanner", _Scanner)
    monkeypatch.setattr(device, "PendantSession", session_cls)
    return device


class _Session:
    entered = 0

    def __init__(self, address):
        pass

    async def __aenter__(self):
        type(self).entered += 1
        return self

    async def __aexit__(self, *exc):
        return None


async def test_ble_not_in_range_never_enters_the_session(monkeypatch):
    class S(_Session):
        entered = 0
    device = _patch(monkeypatch, S, found=False)
    with pytest.raises(device.PendantNotInRange):
        async with device.BlePendant("addr", scan_timeout_s=1):
            pass
    assert S.entered == 0


async def test_ble_not_paired_is_a_distinct_device_error(monkeypatch):
    from pendant_client.ble import PendantNotPairedError

    class S(_Session):
        async def stop_recording(self):
            raise PendantNotPairedError("x")
    device = _patch(monkeypatch, S)
    async with device.BlePendant("addr", scan_timeout_s=1) as p:
        with pytest.raises(DeviceError) as e:
            await p.stop_recording()
    assert str(e.value).startswith("not paired")


async def test_ble_timeout_maps_to_device_error_timeout(monkeypatch):
    class S(_Session):
        async def get_device_status(self):
            raise TimeoutError()
    device = _patch(monkeypatch, S)
    async with device.BlePendant("addr", scan_timeout_s=1) as p:
        with pytest.raises(DeviceError) as e:
            await p.status()
    assert str(e.value) == "timeout" and not isinstance(e.value, device.LinkDropped)


async def test_ble_drain_drop_is_link_dropped_after_delivering_earlier_messages(monkeypatch):
    from bleak.exc import BleakError

    class S(_Session):
        async def download_raw_pendant_messages(self, idle_timeout):
            yield b"a"
            yield b"b"
            raise BleakError("Not connected")
    device = _patch(monkeypatch, S)
    got = []
    async with device.BlePendant("addr", scan_timeout_s=1) as p:
        with pytest.raises(device.LinkDropped):
            async for m in p.drain(idle_s=1):
                got.append(m)
    assert got == [b"a", b"b"]


async def test_ble_command_before_enter_is_not_connected(monkeypatch):
    device = _patch(monkeypatch, _Session)
    p = device.BlePendant("addr", scan_timeout_s=1)
    with pytest.raises(DeviceError, match="not connected"):
        await p.status()


async def test_fake_pendant_drop_raises_link_dropped_and_stays_down():
    from lavalier.device import LinkDropped
    p = FakePendant(messages=[b"a", b"b"], disconnect_after=1)
    async with p:
        with pytest.raises(LinkDropped):
            [m async for m in p.drain(idle_s=5)]
        with pytest.raises(LinkDropped):
            await p.status()


# --- final review fixes: a failed teardown after a good session is logged, not raised ---

@pytest.mark.parametrize("exc", [RuntimeError("cleanup failed"), OSError("gone")])
async def test_ble_teardown_failure_is_logged_and_swallowed(monkeypatch, caplog, exc):
    import logging
    caplog.set_level(logging.INFO)
    class S(_Session):
        async def get_device_status(self):
            from pendant_client.proto import server_pb2
            return server_pb2.DeviceStatus(has_all_fields=True)

        async def __aexit__(self, *e):
            raise exc
    device = _patch(monkeypatch, S)
    async with device.BlePendant("addr", scan_timeout_s=1) as p:
        snap = await p.status()
    assert snap.has_all_fields and "session teardown" in caplog.text


async def test_ble_teardown_does_not_swallow_cancellation(monkeypatch):
    import asyncio

    class S(_Session):
        async def __aexit__(self, *e):
            raise asyncio.CancelledError()
    device = _patch(monkeypatch, S)
    with pytest.raises(asyncio.CancelledError):
        async with device.BlePendant("addr", scan_timeout_s=1):
            pass
