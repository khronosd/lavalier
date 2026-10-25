"""Retrieval for a question across days: terms, the FTS query, the passages and their layout."""

from datetime import date

from conftest import T
from lavalier.config import Config
from lavalier.insights import retrieval
from lavalier.insights.retrieval import Passage, fts_or_query, gather, question_terms, render, sources
from lavalier.journal import Line

DAY = date(2026, 10, 23)
NOW = T(23, 12, 0)


def test_question_terms_keep_the_words_worth_searching_for_in_order_once():
    assert question_terms("What did I decide about retention last week?") == ["decide", "retention"]
    assert question_terms("When did Dana mention the ferry, and the ferry timetable?") == ["dana", "ferry", "timetable"]
    assert question_terms("Who? What? When?") == []
    assert question_terms("  ") == []
    assert question_terms("PS5 or the Xbox") == ["ps5", "xbox"]


def test_fts_query_is_each_term_as_a_quoted_prefix_ored():
    assert fts_or_query(["decide", "retention"]) == '"decide"* OR "retention"*'
    assert fts_or_query(['a"b']) == '"a""b"*'
    assert fts_or_query([]) == ""


def test_gather_finds_the_hit_lines_with_their_context_inside_the_conversation(db, seeded_2026_10_23_subset):
    passages = gather(db, Config(), ["three"], now_ms=NOW)
    assert len(passages) == 1
    p = passages[0]
    assert p.day == DAY and p.conversation_id.startswith("c-20261023-") and p.label is None
    assert [ln.text for ln in p.lines] == ["test test test one two three", "test test test one two three"]
    assert len(p.hits) == 2 and all(h.startswith("clip_") for h in p.hits)
    assert (p.first, p.last, p.total) == (0, 1, 2)
    assert gather(db, Config(), ["zebra"], now_ms=NOW) == []
    assert gather(db, Config(), [], now_ms=NOW) == []


def test_gather_reaches_words_by_prefix(db, seeded_2026_10_23_subset):
    assert gather(db, Config(), ["thr"], now_ms=NOW)
    assert gather(db, Config(), ["tes"], now_ms=NOW)


def test_the_cap_keeps_passages_by_relevance_but_always_the_first(db, seeded_2026_10_23_subset):
    assert len(gather(db, Config(), ["three"], now_ms=NOW, max_chars=1)) == 1


def line(at_ms: int, text: str, seq: int, clip="clip_a") -> Line:
    return Line(at_ms=at_ms, text=text, clip_id=clip, seq=seq)


def test_render_lays_the_passages_out_with_the_day_the_conversation_and_every_line_timed():
    at = lambda h, m, s=0: T(h, m, s)  # conftest's T is the seeded day's clock
    a = Passage(DAY, "c-1", "Firmware standup", at(9, 12), at(9, 15), (line(at(9, 12), "Morning.", 0), line(at(9, 15), "Agreed.", 1)),
                ("clip_a-1",), 0, 1, 5)
    b = Passage(date(2026, 10, 22), "c-2", None, at(17, 33), at(17, 33), (line(at(17, 33), "First words.", 3),), ("clip_a-3",), 3, 3, 4)
    text = render([a, b])
    assert text == (
        "# Friday, 23 October 2026\n"
        "## 09:12 to 09:15 · Firmware standup\n"
        "[09:12:00] Morning.\n"
        "[09:15:00] Agreed.\n"
        "[…]\n"
        "# Thursday, 22 October 2026\n"
        "## 17:33 to 17:33\n"
        "[…]\n"
        "[17:33:00] First words.\n"
    )
    assert render([]) == ""
    assert sources([a, b]) == [
        {"day": "2026-10-23", "conversation_id": "c-1", "line_id": "clip_a-1", "at_ms": at(9, 15)},
        {"day": "2026-10-22", "conversation_id": "c-2", "line_id": "clip_a-3", "at_ms": at(17, 33)},
    ]


def test_the_stopwords_are_lower_case_single_words():
    assert all(w == w.lower() and " " not in w for w in retrieval.STOPWORDS)
