import json
from datetime import date, datetime
from pathlib import Path

from lavalier.connectors import notion_render as nr
from lavalier.insights.schema import FollowUp, Insight
from lavalier.journal import day_view

DAY = date(2026, 10, 23)
GOLDEN = Path(__file__).parent / "golden" / "2026-10-23-notion.json"


def _store(db):
    at = int(datetime(2026, 10, 23, 22, 56, 13).timestamp() * 1000)
    gen = int(datetime(2026, 10, 24, 4, 12).timestamp() * 1000)
    db.set_insight(DAY, provider="anthropic", model="claude-opus-5-5", prompt_version=1, generated_ms=gen,
                   input_chars=100, insight=Insight(
                       "A short pendant test: two rounds of counting to three, both starred.",
                       [FollowUp("Check that both stars landed", at, "clip_20261024T055609.085Z-1"),
                        FollowUp("Call back", None, None)],
                       ["Remy", "Daddy"], ["pendant test", "star button"]))
    return db.insight(DAY)


def _blocks(db, cfg):
    return nr.day_blocks(day_view(db, DAY, cfg, now_ms=0), _store(db))


def test_day_blocks_match_the_golden(db, cfg, seeded_2026_10_23_subset):
    out = json.dumps(_blocks(db, cfg), indent=2, ensure_ascii=False, sort_keys=True)
    if not GOLDEN.exists():  # written once by the setup, then compared exactly
        GOLDEN.write_text(out + "\n", encoding="utf-8")
    assert out + "\n" == GOLDEN.read_text(encoding="utf-8")


def test_the_shape_and_order(db, cfg, seeded_2026_10_23_subset):
    b = _blocks(db, cfg)
    kinds = [x["type"] for x in b]
    assert kinds[0] == "heading_3" and b[0]["heading_3"]["rich_text"][0]["text"]["content"] == "Starred"
    assert all(x["object"] == "block" for x in b)
    texts = nr.plain_text(b).splitlines()
    assert texts.index("Insights") > texts.index("Starred")
    head = next(t for t in texts if "speech" in t)
    assert "–" not in head and " · " not in head and "{#" not in head and not head.startswith("#")
    assert "Call back" in texts
    assert "People: Remy, Daddy" in texts and "Topics: pendant test, star button" in texts
    assert texts[-1] == "Insights by claude-opus-5-5 (Anthropic) at 04:12"


def test_no_insight_and_no_stars(db, cfg, seeded_2026_10_23_subset):
    v = day_view(db, DAY, cfg, now_ms=0)
    assert "Insights" not in nr.plain_text(nr.day_blocks(v, None)).splitlines()
    assert nr.day_blocks(v, None)[0]["heading_3"]["rich_text"][0]["text"]["content"] == "Starred"
    import dataclasses
    assert nr.day_blocks(dataclasses.replace(v, stars=[]), None)[0]["heading_3"]["rich_text"][0]["text"]["content"] != "Starred"


def test_an_error_insight_is_not_rendered(db, cfg, seeded_2026_10_23_subset):
    db.set_insight_error(DAY, provider="anthropic", model="m", prompt_version=1, generated_ms=1, input_chars=1, error="boom")
    v = day_view(db, DAY, cfg, now_ms=0)
    assert nr.day_blocks(v, db.insight(DAY)) == nr.day_blocks(v, None)


def test_plain_text_and_hash_are_stable(db, cfg, seeded_2026_10_23_subset):
    a, b = _blocks(db, cfg), _blocks(db, cfg)
    assert nr.plain_text(a) == nr.plain_text(b) and nr.content_hash(a) == nr.content_hash(b)
    assert len(nr.content_hash(a)) == 64
    c = json.loads(json.dumps(a))
    c[0]["heading_3"]["rich_text"][0]["text"]["content"] = "Changed"
    assert nr.content_hash(c) != nr.content_hash(a)


def test_owned_block_and_plain_text_of_a_callout():
    kid = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "hi"}}]}}
    o = nr.owned_block([kid])
    assert o["type"] == "callout" and o["callout"]["children"] == [kid]
    assert o["callout"]["icon"] == {"type": "emoji", "emoji": "🎙"}
    assert o["callout"]["rich_text"][0]["text"]["content"] == nr.OWNED_MARKER
    assert nr.plain_text([o]) == nr.OWNED_MARKER + "\nhi"


def test_split_runs_boundaries():
    assert nr.split_runs("") == []
    assert nr.split_runs("a\nb") == ["a\nb"]
    line = "x" * 999
    runs = nr.split_runs("\n".join([line] * 5))
    assert runs == [(line + "\n") * 2, (line + "\n") * 2, line]
    assert nr.split_runs("y" * 2000) == ["y" * 2000]
    assert nr.split_runs("y" * 4500) == ["y" * 2000, "y" * 2000, "y" * 500]
    assert nr.split_runs("\n".join(["z" * 1999] * 3)) == ["z" * 1999 + "\n"] * 2 + ["z" * 1999]


def test_a_50k_conversation_fits_in_under_100_runs_uncut():
    runs = nr.split_runs("\n".join(f"[00:00:00] {'w' * 80}" for _ in range(600)))
    assert len(runs) <= nr.MAX_RUNS and "[… cut]" not in runs and all(len(r) <= nr.RUN_CHARS for r in runs)


def test_a_huge_conversation_is_cut_to_100_runs():
    runs = nr.split_runs("\n".join(f"[00:00:00] {'w' * 80}" for _ in range(5000)))
    assert len(runs) == nr.MAX_RUNS and runs[-1] == "[… cut]"
    assert all(len(r) <= nr.RUN_CHARS for r in runs)


def test_a_conversation_paragraph_never_exceeds_the_limits(db, cfg, seeded_2026_10_23_subset):
    import dataclasses
    v = day_view(db, DAY, cfg, now_ms=0)
    conv = v.conversations[0]
    fat = dataclasses.replace(conv, lines=[dataclasses.replace(conv.lines[0], text="q" * 60_000)])
    for blk in nr.day_blocks(dataclasses.replace(v, conversations=[fat]), None):
        rt = blk[blk["type"]]["rich_text"]
        assert len(rt) <= 100 and all(len(r["text"]["content"]) <= 2000 for r in rt)


def test_properties(db, cfg, seeded_2026_10_23_subset):
    v = day_view(db, DAY, cfg, now_ms=0)
    p = nr.page_properties(v)
    assert p == {"Date": {"date": {"start": "2026-10-23"}}, "Speech (min)": {"number": round(v.speech_ms / 60000)},
                 "Conversations": {"number": len(v.conversations)}, "Stars": {"number": len(v.stars)}}
    assert nr.property_schema() == {"Date": {"date": {}}, "Speech (min)": {"number": {"format": "number"}},
                                    "Conversations": {"number": {"format": "number"}}, "Stars": {"number": {"format": "number"}}}
    assert nr.page_title(DAY) == "2026-10-23"


def test_runs_joined_are_the_text():
    text = "\n".join(f"[00:00:{i % 60:02d}] {'v' * (i % 90)}" for i in range(300))
    assert len(text) > 10_000
    runs = nr.split_runs(text)
    assert "".join(runs) == text and all(len(r) <= nr.RUN_CHARS for r in runs)
    assert all(r.endswith("\n") for r in runs[:-1])
    assert "".join(nr.split_runs("\nabc\n\nd\n")) == "\nabc\n\nd\n"
    assert nr.split_runs("\nabc") == ["\nabc"]


def test_same_minute_heading_is_the_start_alone_in_notion_only(db, cfg, seeded_2026_10_23_subset):
    v = day_view(db, DAY, cfg, now_ms=0)
    assert "22:56, 16 s speech ★★" in nr.plain_text(nr.day_blocks(v, None)).splitlines()


def test_a_multiline_star_quote_stays_one_line(db, cfg, seeded_2026_10_23_subset):
    import dataclasses
    v = day_view(db, DAY, cfg, now_ms=0)
    star = dataclasses.replace(v.stars[0], quote="one\ntwo")
    b = nr.day_blocks(dataclasses.replace(v, stars=[star]), None)
    assert b[1]["bulleted_list_item"]["rich_text"][0]["text"]["content"].endswith("— one two")
