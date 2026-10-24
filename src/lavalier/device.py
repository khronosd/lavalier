"""The seam between the recorder and the pendant: a small async protocol and its BLE adapter.

This is the only module that imports the fork's session or BLE helpers. The adapter is thin:
no retries, no policy, no sleeping. Policy belongs to the sync engine.
"""

from collections.abc import AsyncIterator, Callable
from typing import Protocol

from bleak import BleakScanner
from bleak.exc import BleakError
from pendant_client.ble import PendantNotPairedError, is_disconnect_exception, suppress_disconnect
from pendant_client.proto import shared_pb2
from pendant_client.session import PendantSession

from lavalier.db import now_ms
from lavalier.models import DeviceSnapshot


class PendantNotInRange(Exception):
    """The pendant is not advertising."""


class DeviceError(Exception):
    """Any other failure talking to the pendant."""


class LinkDropped(DeviceError):
    """The BLE link went away mid-command or mid-stream; what was already delivered is kept."""


class Pendant(Protocol):
    async def __aenter__(self) -> "Pendant": ...
    async def __aexit__(self, *exc) -> None: ...
    async def set_time(self, unix_ms: int) -> None: ...
    async def info(self) -> tuple[str, int]: ...  # (firmware_ver, storage_instance)
    async def status(self) -> DeviceSnapshot: ...  # firmware/storage_instance filled by the caller
    async def stop_recording(self) -> None: ...
    async def start_recording(self) -> None: ...
    def drain(self, *, idle_s: float) -> AsyncIterator[bytes]: ...  # raw PendantAllMsg payloads


# The only session methods the recorder may ever call (enforced by tests/test_closed_command_set.py).
ALLOWED_SESSION_CALLS = frozenset({
    "get_device_info",
    "get_device_status",
    "set_current_time_ms",
    "stop_recording",
    "start_recording",
    "download_raw_pendant_messages",
})


def snapshot_from_status(ds, *, read_at_ms: int, firmware_ver: str = "", storage_instance: int = 0) -> DeviceSnapshot:
    return DeviceSnapshot(
        read_at_ms=read_at_ms,
        has_all_fields=bool(ds.has_all_fields),
        recording_state=shared_pb2.EnumC11643f.Name(ds.recording_status.recording_state),
        oldest_page=ds.storage_state.oldest_flash_page,
        newest_page=ds.storage_state.newest_flash_page,
        soc=ds.battery_status.soc,
        current_ma=ds.battery_status.current,
        usb_state=shared_pb2.Usb.Name(ds.battery_status.usb_state),
        firmware_ver=firmware_ver,
        storage_instance=storage_instance,
    )


_FORK_ERRORS = (BleakError, OSError, EOFError, RuntimeError)


def _map_error(exc: BaseException) -> DeviceError:
    if is_disconnect_exception(exc):
        return LinkDropped("link dropped")
    if isinstance(exc, PendantNotPairedError):
        return DeviceError(f"not paired: {exc}" if str(exc) else "not paired")
    if isinstance(exc, TimeoutError):
        return DeviceError("timeout")
    detail = str(exc)
    return DeviceError(f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__)


class BlePendant:
    def __init__(self, address: str, *, scan_timeout_s: float, clock: Callable[[], int] = now_ms):
        self._address = address
        self._scan_timeout_s = scan_timeout_s
        self._clock = clock
        self._session = None

    async def __aenter__(self) -> "BlePendant":
        try:
            found = await BleakScanner.find_device_by_address(self._address, timeout=self._scan_timeout_s)
        except _FORK_ERRORS as exc:
            raise _map_error(exc) from exc
        if found is None:
            raise PendantNotInRange(self._address)
        session = PendantSession(self._address)
        try:
            self._session = await session.__aenter__()
        except _FORK_ERRORS as exc:
            raise _map_error(exc) from exc
        return self

    async def __aexit__(self, *exc) -> None:
        session, self._session = self._session, None
        if session is not None:
            # a teardown that fails after a good session (a dropped link, most often) is logged
            # and swallowed: it must not turn a finished drain into an error
            await suppress_disconnect(session.__aexit__(*exc), what="session teardown")

    def _require(self):
        if self._session is None:
            raise DeviceError("not connected")
        return self._session

    async def set_time(self, unix_ms: int) -> None:
        _session = self._require()
        try:
            await _session.set_current_time_ms(unix_ms)
        except _FORK_ERRORS as exc:
            raise _map_error(exc) from exc

    async def info(self) -> tuple[str, int]:
        _session = self._require()
        try:
            di = await _session.get_device_info()
        except _FORK_ERRORS as exc:
            raise _map_error(exc) from exc
        return di.firmware_ver, int(di.raw.storage_instance)

    async def status(self) -> DeviceSnapshot:
        _session = self._require()
        try:
            ds = await _session.get_device_status()
        except _FORK_ERRORS as exc:
            raise _map_error(exc) from exc
        return snapshot_from_status(ds, read_at_ms=self._clock())

    async def stop_recording(self) -> None:
        _session = self._require()
        try:
            await _session.stop_recording()
        except _FORK_ERRORS as exc:
            raise _map_error(exc) from exc

    async def start_recording(self) -> None:
        _session = self._require()
        try:
            await _session.start_recording()
        except _FORK_ERRORS as exc:
            raise _map_error(exc) from exc

    async def drain(self, *, idle_s: float) -> AsyncIterator[bytes]:
        _session = self._require()
        try:
            async for payload in _session.download_raw_pendant_messages(idle_timeout=idle_s):
                yield payload
        except _FORK_ERRORS as exc:
            raise _map_error(exc) from exc
