import hashlib

from pendant_client.decode import StoragePage

from pendant_recorder.models import PageKey
from pendant_recorder.pages import import_capture, page_key


def test_page_key_hashes_flash_page_bytes():
    sp = StoragePage(run=2, session=1, index=5, seq=0, ingest_type=2, flash_page_error=0, flash_page=b"\x08\x01")
    assert page_key(sp) == PageKey(2, 5, hashlib.sha256(b"\x08\x01").hexdigest())


def test_import_twice_adds_nothing_new(root, db, capture_file):
    r1 = import_capture(db, root, capture_file)
    r2 = import_capture(db, root, capture_file)
    assert (r1.pages_new, r1.pages_duplicate) == (3, 0) and (r2.pages_new, r2.pages_duplicate) == (0, 3)
    assert r2.capture_id == r1.capture_id and r2.new_payloads == []


def test_overlapping_captures_dedup_by_key(root, db, make_capture):
    a = make_capture(pages=[1, 2, 3]); b = make_capture(pages=[3, 4])
    import_capture(db, root, a); r = import_capture(db, root, b)
    assert (r.pages_new, r.pages_duplicate) == (1, 1)


def test_same_index_different_bytes_is_new(root, db, make_capture):
    import_capture(db, root, make_capture(pages=[9], opus=b"A"*40))
    r = import_capture(db, root, make_capture(pages=[9], opus=b"B"*40))
    assert r.pages_new == 1
