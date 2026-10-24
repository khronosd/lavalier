from pendant_recorder.models import Segment, Transcript, Word
from pendant_recorder.noise import classify


def test_rec0099_is_speech(cfg, clip_at):
    t = Transcript("test test test one two three", "en", "m", [Segment(0, 2.32, "…", -0.293, 0.0, [Word(0,0,"test",0.49), Word(0,0,"test",0.85), Word(0,0,"test",0.98), Word(0,0,"one",0.50), Word(0,0,"two",0.93), Word(0,0,"three",1.0)])])
    assert classify(clip_at(mean_db=-27.2), t, cfg) == "speech"


def test_rec0098_thank_you_is_noise(cfg, clip_at):
    t = Transcript("Thank you.", "en", "m", [Segment(0, 1.88, " Thank you.", -0.953, 0.0, [Word(0,0.28,"Thank",0.05), Word(0.28,1.88,"you.",0.99)])])
    assert classify(clip_at(mean_db=-44.2), t, cfg) == "noise"


def test_quiet_but_confident_is_still_noise_by_loudness(cfg, clip_at):
    t = Transcript("ok ok", "en", "m", [Segment(0, 1, "ok ok", -0.1, 0.0, [Word(0,0,"ok",0.9), Word(0,0,"ok",0.9)])])
    assert classify(clip_at(mean_db=-41.0), t, cfg) == "noise"


def test_no_loudness_measured_falls_back_to_transcript(cfg, clip_at):
    t = Transcript("ok ok", "en", "m", [Segment(0, 1, "ok ok", -0.1, 0.0, [Word(0,0,"ok",0.9), Word(0,0,"ok",0.9)])])
    assert classify(clip_at(mean_db=None), t, cfg) == "speech"
