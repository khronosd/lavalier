"""Scripted stand-in for the pendant, driven by the sync engine, CLI and app tests."""

from typing import Callable, Optional

from lavalier.device import LinkDropped, PendantNotInRange
from lavalier.models import DeviceSnapshot


class FakePendant:
    def __init__(self, *, state="LISTENING", pages=(0, 786), soc=94, current_ma=-10, usb="USB_DISCONNECTED",
                 firmware="1.1.3", storage_instance=7, partial=False, in_range=True,
                 messages: list[bytes] = (), disconnect_after: Optional[int] = None,
                 start_result="LISTENING", stop_result="NOT_RECORDING", clock=lambda: 1_000_000,
                 fail_on: Optional[dict[str, Exception]] = None, partial_after_stop: bool = False):
        self.state = state
        self.pages = pages
        self.soc = soc
        self.current_ma = current_ma
        self.usb = usb
        self.firmware = firmware
        self.storage_instance = storage_instance
        self.partial = partial
        self.in_range = in_range
        self.messages = list(messages)
        self.disconnect_after = disconnect_after
        self.start_result = start_result
        self.stop_result = stop_result
        self.clock = clock
        self.log: list[str] = []
        self.acked: list[int] = []
        self.on_ack: Optional[Callable[[int], None]] = None
        # "name" fails the first command logged as name, "name#n" its n-th; each fires once, after the
        # command took effect (a write that landed before the link went). A LinkDropped takes the link down.
        self.fail_on = dict(fail_on or {})
        self.partial_after_stop = partial_after_stop
        self._down = False

    def _after(self, name: str) -> None:
        n = sum(1 for e in self.log if e.split(":")[0] == name)
        exc = self.fail_on.pop(f"{name}#{n}", None) or (self.fail_on.pop(name, None) if n == 1 else None)
        if exc is not None:
            if isinstance(exc, LinkDropped):
                self._down = True
            raise exc

    async def __aenter__(self):
        if not self.in_range:
            raise PendantNotInRange("fake")
        self._down = False
        self.log.append("enter")
        return self

    async def __aexit__(self, *exc) -> None:
        self._down = False
        self.log.append("exit")

    def _check(self) -> None:
        if self._down:
            raise LinkDropped("link dropped")

    async def set_time(self, unix_ms: int) -> None:
        self._check()
        self.log.append(f"set_time:{unix_ms}")
        self._after("set_time")

    async def info(self) -> tuple[str, int]:
        self._check()
        self.log.append("info")
        self._after("info")
        return self.firmware, self.storage_instance

    async def status(self) -> DeviceSnapshot:
        self._check()
        self.log.append("status")
        self._after("status")
        return DeviceSnapshot(
            read_at_ms=self.clock(),
            has_all_fields=not self.partial,
            recording_state="NOT_RECORDING" if self.partial else self.state,
            oldest_page=self.pages[0],
            newest_page=self.pages[1],
            soc=self.soc,
            current_ma=self.current_ma,
            usb_state=self.usb,
            firmware_ver="",
            storage_instance=0,
        )

    async def stop_recording(self) -> None:
        self._check()
        self.log.append("stop")
        self.state = self.stop_result
        if self.partial_after_stop:
            self.partial = True
        self._after("stop")

    async def start_recording(self) -> None:
        self._check()
        self.log.append("start")
        self.state = self.start_result
        self._after("start")

    async def drain(self, *, idle_s: float):
        from google.protobuf.message import DecodeError
        from pendant_client.decode import storage_page_of

        self._check()
        self.log.append("drain")
        for n, msg in enumerate(self.messages):
            if self.disconnect_after is not None and n >= self.disconnect_after:
                self._down = True
                raise LinkDropped("link dropped")
            yield msg
            try:
                page = storage_page_of(msg)
            except DecodeError:
                page = None  # opaque test bytes are not storage pages
            if page is not None:
                self.log.append(f"ack:{page.index}")
                self.acked.append(page.index)
                if self.on_ack is not None:
                    self.on_ack(page.index)
