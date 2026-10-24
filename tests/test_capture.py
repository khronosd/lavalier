import asyncio

from pendant_client.decode import iter_messages_from_bin

from fake_pendant import FakePendant
from lavalier.capture import CaptureSink


def test_sink_counts_pages_and_names_the_file_in_utc(root, two_storage_payloads):
    root.ensure()
    s = CaptureSink(root, ble_identifier="ADDR", fsync_every=100, started_ms=1792821367981)   # 2026-10-24T05:56:07Z
    for p in two_storage_payloads: s.add(p)
    cf = s.close(complete=True)
    assert cf.path.name == "20261024T055607Z.bin" and (cf.messages, cf.pages, cf.first_page, cf.last_page, cf.complete) == (2, 2, 10, 11, True)
    assert list(iter_messages_from_bin(cf.path)) == two_storage_payloads


def test_empty_drain_leaves_no_file(root):
    root.ensure()
    s = CaptureSink(root, ble_identifier="ADDR", fsync_every=100, started_ms=0)
    assert s.close(complete=True) is None and not list(root.captures.iterdir())


def test_every_ack_finds_its_page_already_on_disk(root, two_storage_payloads):
    root.ensure()
    s = CaptureSink(root, ble_identifier="ADDR", fsync_every=1, started_ms=0)
    p = FakePendant(messages=two_storage_payloads)
    seen_at_ack = []
    p.on_ack = lambda index: seen_at_ack.append((index, len(list(iter_messages_from_bin(s.path)))))
    async def go():
        async with p:
            async for m in p.drain(idle_s=5): s.add(m)
    asyncio.run(go())
    s.close(complete=True)
    assert seen_at_ack == [(10, 1), (11, 2)]


def test_incomplete_capture_keeps_what_was_written(root, two_storage_payloads):
    root.ensure()
    s = CaptureSink(root, ble_identifier="ADDR", fsync_every=100, started_ms=0)
    s.add(two_storage_payloads[0])
    cf = s.close(complete=False)
    assert cf.complete is False and cf.pages == 1 and list(iter_messages_from_bin(cf.path)) == two_storage_payloads[:1]
