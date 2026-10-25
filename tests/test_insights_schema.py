from datetime import date, datetime

import pytest

from lavalier.insights.schema import INSIGHT_SCHEMA, PROMPT_VERSION, FollowUp, InsightError, parse_reply


def test_parse_reply_maps_times_to_the_day_and_drops_empty_strings():
    i = parse_reply({"summary": " A day. ", "follow_ups": [{"text": "Call Remy", "time": "17:42:03"}, {"text": "", "time": "00:00:00"}],
                     "people": ["Remy", "Remy", ""], "topics": ["retention"]}, date(2026, 10, 23))
    at = int(datetime(2026, 10, 23, 17, 42, 3).timestamp() * 1000)
    assert i.summary == "A day." and i.follow_ups == [FollowUp("Call Remy", at, None)] and i.people == ["Remy"]
    assert i.topics == ["retention"]


def test_parse_reply_dedups_keeping_order_and_strips():
    i = parse_reply({"summary": "s", "follow_ups": [], "people": [" B ", "A", "B"], "topics": ["x", "x "]}, date(2026, 10, 23))
    assert i.people == ["B", "A"] and i.topics == ["x"]


def test_parse_reply_names_the_first_bad_field():
    with pytest.raises(InsightError, match="follow_ups"):
        parse_reply({"summary": "x", "follow_ups": "no", "people": [], "topics": []}, date(2026, 10, 23))


@pytest.mark.parametrize("data, field", [
    ("nope", "reply"),
    ({"follow_ups": [], "people": [], "topics": []}, "summary"),
    ({"summary": 3, "follow_ups": [], "people": [], "topics": []}, "summary"),
    ({"summary": "x", "follow_ups": [], "people": "a", "topics": []}, "people"),
    ({"summary": "x", "follow_ups": [], "people": [], "topics": [1]}, "topics[0]"),
    ({"summary": "x", "follow_ups": [1], "people": [], "topics": []}, "follow_ups[0]"),
    ({"summary": "x", "follow_ups": [{"text": 1, "time": "00:00:00"}], "people": [], "topics": []}, "follow_ups[0].text"),
    ({"summary": "x", "follow_ups": [{"text": "a", "time": "5pm"}], "people": [], "topics": []}, "follow_ups[0].time"),
    ({"summary": "x", "follow_ups": [{"text": "a", "time": "25:00:00"}], "people": [], "topics": []}, "follow_ups[0].time"),
    ({"summary": "x", "follow_ups": [{"text": "a", "time": "12:00:00"}, {"text": "b"}], "people": [], "topics": []}, "follow_ups[1].time"),
])
def test_parse_reply_rejects_bad_shapes_naming_the_field(data, field):
    with pytest.raises(InsightError, match=field.replace("[", r"\[").replace("]", r"\]")):
        parse_reply(data, date(2026, 10, 23))


def test_schema_is_strict_at_every_object_level():
    assert PROMPT_VERSION == 1
    assert INSIGHT_SCHEMA["additionalProperties"] is False
    assert INSIGHT_SCHEMA["required"] == ["summary", "follow_ups", "people", "topics"]
    item = INSIGHT_SCHEMA["properties"]["follow_ups"]["items"]
    assert item["additionalProperties"] is False and item["required"] == ["text", "time"]


def test_parse_reply_uses_the_local_wall_clock_on_a_dst_day():
    # US Pacific ends DST on 2026-11-01: 12:00 local is 13 hours after local midnight, not 12.
    d = date(2026, 11, 1)
    i = parse_reply({"summary": "s", "follow_ups": [{"text": "a", "time": "12:00:00"}], "people": [], "topics": []}, d)
    assert i.follow_ups[0].at_ms == int(datetime(2026, 11, 1, 12, 0, 0).timestamp() * 1000)
    midnight_ms = int(datetime(2026, 11, 1).timestamp() * 1000)
    assert i.follow_ups[0].at_ms - midnight_ms == 13 * 3_600_000


def test_times_are_ascii_digits_only():
    assert "[0-9]" in INSIGHT_SCHEMA["properties"]["follow_ups"]["items"]["properties"]["time"]["pattern"]
    with pytest.raises(InsightError, match="time"):
        parse_reply({"summary": "s", "follow_ups": [{"text": "a", "time": "\u0661\u0662:\u0663\u0664:\u0665\u0666"}], "people": [], "topics": []},
                    date(2026, 10, 23))
