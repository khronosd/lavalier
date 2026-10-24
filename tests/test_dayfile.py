from datetime import date
from pathlib import Path

from conftest import T
from pendant_recorder.dayfile import render_day, write_day


def test_render_matches_golden(root, db, cfg, seeded_2026_10_23_subset):
    out = render_day(db, date(2026, 10, 23), cfg, now_ms=T(23, 30, 0))
    assert out == (Path(__file__).parent / "golden" / "2026-10-23.md").read_text()


def test_clock_suspect_note(root, db, cfg, seeded_bad_clock_day):
    assert "> Clock was unset on the pendant" in render_day(db, date(2026, 10, 24), cfg, now_ms=0)


def test_orphan_star_line(root, db, cfg, seeded_orphan_star):
    assert "★ (no speech recorded nearby)" in render_day(db, date(2026, 10, 23), cfg, now_ms=0)


def test_write_day_marks_clean(root, db, cfg, seeded_2026_10_23_subset):
    db.mark_day_dirty(date(2026, 10, 23)); p = write_day(db, root, date(2026, 10, 23), cfg, now_ms=0)
    assert p.name == "2026-10-23.md" and db.days_dirty() == []
