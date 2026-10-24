import pytest
import hashlib

from pendant_client.decode import StoragePage

from pendant_recorder.models import PageKey
from pendant_recorder.pages import import_capture, page_key


def test_page_key_hashes_flash_page_bytes():
    sp = StoragePage(run=2, session=1, index=5, seq=0, ingest_type=2, flash_page_error=0, flash_page=b"\x08\x01")
    assert page_key(sp) == PageKey(2, 5, hashlib.sha256(b"\x08\x01").hexdigest())


def test_import_twice_adds_nothing_new(root, db, capture_file):
    r1 = import_capture(db, root, capture_file)
    db.mark_capture_decoded(r1.capture_id)
    r2 = import_capture(db, root, capture_file)
    assert (r1.pages_new, r1.pages_duplicate) == (3, 0) and (r2.pages_new, r2.pages_duplicate) == (0, 3)
    assert r2.capture_id == r1.capture_id and r2.new_payloads == []


def test_reimport_of_undecoded_capture_returns_its_pages(root, db, capture_file):
    r1 = import_capture(db, root, capture_file)
    r2 = import_capture(db, root, capture_file)  # never decoded: decode must get another go
    assert (r2.pages_new, r2.pages_duplicate) == (0, 3)
    assert r2.capture_id == r1.capture_id and r2.new_payloads == r1.new_payloads


def test_overlapping_captures_dedup_by_key(root, db, make_capture):
    a = make_capture(pages=[1, 2, 3]); b = make_capture(pages=[3, 4])
    import_capture(db, root, a); r = import_capture(db, root, b)
    assert (r.pages_new, r.pages_duplicate) == (1, 1)


def test_same_index_different_bytes_is_new(root, db, make_capture):
    import_capture(db, root, make_capture(pages=[9], opus=b"A"*40))
    r = import_capture(db, root, make_capture(pages=[9], opus=b"B"*40))
    assert r.pages_new == 1


def test_crash_mid_import_leaves_nothing_and_retry_is_complete(root, db, tmp_path, monkeypatch):
    from pendant_client.decode import write_batch_ingest_request
    from builders import make_audio_flash_page, make_button_page, make_storage_buffer_msg
    from pendant_recorder.db import Database

    button = make_storage_buffer_msg(page_index=0, flash_page=make_button_page(1000), session=1, run=1)
    msgs = [button] + [
        make_storage_buffer_msg(page_index=i, flash_page=make_audio_flash_page(b"\xb8" + b"A" * 39), session=1, run=1)
        for i in (1, 2)
    ]
    path = tmp_path / "mixed.bin"
    write_batch_ingest_request(messages=msgs, ble_identifier="t", path=path)

    real = Database.add_page
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(self, *a, **k)

    monkeypatch.setattr(Database, "add_page", flaky)
    with pytest.raises(RuntimeError):
        import_capture(db, root, path)
    monkeypatch.setattr(Database, "add_page", real)

    r = import_capture(db, root, path)
    assert (r.pages_new, r.pages_duplicate) == (3, 0)
    assert r.new_payloads == msgs


def test_truncated_existing_copy_is_replaced(root, db, capture_file):
    root.ensure()
    sha = hashlib.sha256(capture_file.read_bytes()).hexdigest()
    root.captures.mkdir(parents=True, exist_ok=True)
    dest = root.captures / f"{sha[:12]}-{capture_file.name}"
    dest.write_bytes(capture_file.read_bytes()[:10])
    r = import_capture(db, root, capture_file)
    assert dest.read_bytes() == capture_file.read_bytes()
    assert r.pages_new == 3


def test_capture_path_is_stored_relative_to_the_state_root(root, db, capture_file):
    r = import_capture(db, root, capture_file)
    db.mark_capture_decoded(r.capture_id)
    sha = hashlib.sha256(capture_file.read_bytes()).hexdigest()
    assert db.captures_decoded_before(2**62) == [(r.capture_id, f"captures/{sha[:12]}-{capture_file.name}")]
