from dataclasses import replace

from lavalier.models import Transcript
from lavalier.retention import deadline_ms, sweep


def test_deadline_rules(cfg, clip_at):
    day_ms = 86_400_000
    assert deadline_ms(clip_at(transcribed_at=1000, classification="speech"), cfg,
                       protected=False) == 1000 + 14 * day_ms
    assert deadline_ms(clip_at(transcribed_at=1000, classification="speech"), cfg, protected=True) is None
    assert deadline_ms(clip_at(transcribed_at=1000, classification="failed"), cfg, protected=False) is None
    assert deadline_ms(clip_at(transcribed_at=None), cfg, protected=False) is None
    assert deadline_ms(clip_at(transcribed_at=1000, classification="speech"),
                       replace(cfg, retention_days=0), protected=False) == 1000


def test_sweep_deletes_only_expired_unstarred(root, db, cfg, seeded_retention_day):
    old, starred, fresh, failed = seeded_retention_day
    n_clips, _ = sweep(db, root, cfg, now_ms=old.transcribed_at + 15 * 86_400_000)
    assert n_clips == 1 and not (root.root / old.path).exists()
    assert all((root.root / c.path).exists() for c in (starred, fresh, failed))
    assert db.clip(old.clip_id).path == "" and db.days_dirty() == [old.day]


def test_pinned_survives(root, db, cfg, seeded_retention_day):
    old, *_ = seeded_retention_day
    db.pin(db.conversations_for_day(old.day)[0].conversation_id)
    assert sweep(db, root, cfg, now_ms=old.transcribed_at + 15 * 86_400_000) == (0, 0)


def test_sweep_deletes_capture_file_once_clips_are_gone(root, db, cfg, clip_record):
    root.ensure()
    f = root.captures / "a.bin"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x")
    cid = db.add_capture(str(f), "sha", 1, True)
    db.mark_capture_decoded(cid)
    db.add_clip(replace(clip_record, capture_id=cid))
    far = 10**15
    assert sweep(db, root, cfg, now_ms=far) == (0, 0) and f.exists()  # clip untranscribed, still has audio
    db.clear_clip_path(clip_record.clip_id)
    assert sweep(db, root, cfg, now_ms=far) == (0, 1) and not f.exists()
    assert sweep(db, root, cfg, now_ms=far) == (0, 0)  # already gone: not counted


def test_sweep_resolves_a_relative_capture_path_under_the_root(root, db, cfg):
    root.ensure()
    f = root.captures / "rel.bin"
    f.write_bytes(b"x")
    db.mark_capture_decoded(db.add_capture("captures/rel.bin", "sha-rel", 1, True))
    assert sweep(db, root, cfg, now_ms=10**15) == (0, 1) and not f.exists()


def test_sweep_never_deletes_outside_the_state_root(root, db, cfg, clip_record, tmp_path, caplog):
    root.ensure()
    outside_clip = tmp_path / "outside.opus"
    outside_clip.write_bytes(b"keep me")
    outside_capture = tmp_path / "outside.bin"
    outside_capture.write_bytes(b"keep me too")
    db.add_clip(replace(clip_record, path="../outside.opus", capture_id=99))
    db.set_transcript(clip_record.clip_id, Transcript("", "en", "m", []), "noise", 1)
    db.mark_capture_decoded(db.add_capture(str(outside_capture), "sha-out", 1, True))
    with caplog.at_level("WARNING"):
        assert sweep(db, root, cfg, now_ms=10**15) == (0, 0)
    assert outside_clip.exists() and outside_capture.exists()
    assert db.clip(clip_record.clip_id).path == "../outside.opus"
    assert caplog.text.count("outside the state root") == 2


def test_sweep_evicts_the_aac_cache(root, db, cfg, seeded_retention_day):
    import shutil
    if not shutil.which("ffmpeg"):
        import pytest
        pytest.skip("ffmpeg missing")
    from lavalier.playback import aac_path
    old = seeded_retention_day[0]
    aac_path(db, root, old.clip_id)
    cached = root.cache / "aac" / f"{old.clip_id}.m4a"
    assert cached.exists()
    sweep(db, root, cfg, now_ms=old.transcribed_at + 15 * 86_400_000)
    assert not cached.exists()


def test_a_cache_eviction_failure_does_not_abort_the_sweep(root, db, cfg, seeded_retention_day, monkeypatch, caplog):
    import logging
    from lavalier import retention
    old, *_ = seeded_retention_day

    def broken(paths, clip_id):
        raise PermissionError("cache is read-only")
    monkeypatch.setattr(retention, "evict", broken)
    with caplog.at_level(logging.WARNING, logger="lavalier.retention"):
        assert sweep(db, root, cfg, now_ms=old.transcribed_at + 15 * 86_400_000) == (1, 0)
    assert db.clip(old.clip_id).path == "" and "cache is read-only" in caplog.text
