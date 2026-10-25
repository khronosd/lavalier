"""The insights stage: one day's text to the chosen provider, the reply stored, the day file rewritten."""

from datetime import date, datetime, time, timedelta
from typing import Optional

from lavalier.config import Config
from lavalier.dayfile import write_dirty_days
from lavalier.db import Database, InsightRecord
from lavalier.insights.keys import KeychainError
from lavalier.insights.names import provider_id
from lavalier.insights import retrieval
from lavalier.insights.prompt import DayText, day_text, resolve_moment
from lavalier.insights.providers.base import Provider, ProviderError
from lavalier.insights.schema import PROMPT_VERSION, FollowUp, Insight, InsightError, parse_reply
from lavalier.journal import day_view
from lavalier.paths import Paths

NO_SPEECH = "Nothing to summarise for this day"
NO_MATCH = "Nothing in your days matches the words of that question."
DAY_COMPLETE_HOUR = 4


def _complete_ms(day: date) -> int:
    """04:00 local on the day after `day`, in epoch ms."""
    return int(datetime.combine(day + timedelta(days=1), time(DAY_COMPLETE_HOUR, 0)).astimezone().timestamp() * 1000)


def day_is_complete(day: date, now_ms: int) -> bool:
    return now_ms > _complete_ms(day)


def due_days(db: Database, cfg: Config, *, now_ms: int, enabled_at_ms: Optional[int]) -> list[date]:
    """Complete speech days without any insight row that completed after a provider was chosen; oldest first.
    A day is due only once its audio is in: a successful drain ended after the day completed (the evening
    may still be on the pendant until then), and none of its clips still waits for a transcript."""
    if not cfg.insights_auto or not cfg.insights_provider or enabled_at_ms is None:
        return []
    drained = db.last_drain_ok_ms()
    if drained is None:
        return []
    pending = db.days_needing_transcript()
    today = datetime.fromtimestamp(now_ms / 1000).date()
    return [d for d in db.days_with_speech()
            if d != today and day_is_complete(d, now_ms) and _complete_ms(d) >= enabled_at_ms
            and drained > _complete_ms(d) and d not in pending and db.insight(d) is None]


def _provider_string(provider: Provider) -> str:
    """What the row records as its provider: `openai@<host>` for an endpoint, else the provider's name."""
    return provider_id(provider.name, getattr(provider, "base_url", "") or "")


def _failed(db: Database, provider: Provider, day: date, *, now_ms: int, chars: int, truncated: bool,
            error: str, store: bool = True) -> InsightRecord:
    """The error record. It is stored only when the day has no done row, so a failed regenerate never
    takes away a good insight; otherwise it is returned without being stored."""
    rec = InsightRecord(day, "error", _provider_string(provider), provider.model, PROMPT_VERSION, now_ms, chars, None, error,
                        truncated)
    existing = db.insight(day)
    if store and (existing is None or existing.state != "done"):
        db.set_insight_error(day, provider=_provider_string(provider), model=provider.model, prompt_version=PROMPT_VERSION,
                             generated_ms=now_ms, input_chars=chars, error=error, truncated=truncated)
        return db.insight(day)
    return rec


def generate_day(db: Database, paths: Paths, cfg: Config, provider: Provider, day: date, *,
                 now_ms: int) -> InsightRecord:
    """Summarise one day. Provider, reply and Keychain problems become an error record, never an exception,
    and leave the day file as it was. A day without speech stores nothing, so pressing Generate before any
    speech cannot keep the day from its later automatic send."""
    dt = day_text(db, day, cfg, now_ms=now_ms)
    fail = dict(now_ms=now_ms, chars=dt.chars, truncated=dt.truncated)
    if not dt.has_speech:
        return _failed(db, provider, day, error=NO_SPEECH, store=False, **fail)
    try:
        insight = parse_reply(provider.summarize(dt), day)
    except (ProviderError, InsightError, KeychainError) as e:
        return _failed(db, provider, day, error=str(e), **fail)

    view = day_view(db, day, cfg, now_ms=now_ms)
    ups = [FollowUp(f.text, f.at_ms, resolve_moment(view, f.at_ms) if f.at_ms is not None else None)
           for f in insight.follow_ups]
    insight = Insight(insight.summary, ups, insight.people, insight.topics)
    with db.transaction():  # the row and the dirty mark land together; the file is written after the commit
        db.set_insight(day, provider=_provider_string(provider), model=provider.model, prompt_version=PROMPT_VERSION,
                       generated_ms=now_ms, input_chars=dt.chars, insight=insight, truncated=dt.truncated)
        db.mark_day_dirty(day)
    write_dirty_days(db, paths, cfg, now_ms=now_ms)
    return db.insight(day)


def ask_day(db: Database, cfg: Config, provider: Provider, day: date, question: str, *, now_ms: int) -> str:
    dt = day_text(db, day, cfg, now_ms=now_ms)
    if not dt.has_speech:
        return NO_SPEECH
    return provider.ask(dt, question)


def ask_days(db: Database, cfg: Config, provider: Provider, question: str, *, now_ms: int) -> dict:
    """A question across every day: the passages whose words match it go to the provider, each under its
    day and time; the answer comes back with its sources. Nothing matching sends nothing."""
    terms = retrieval.question_terms(question)
    passages = retrieval.gather(db, cfg, terms, now_ms=now_ms) if terms else []
    if not passages:
        return {"answer": NO_MATCH, "sources": [], "days": 0}
    text = retrieval.render(passages)
    newest = max(p.day for p in passages)
    start = int(datetime.combine(newest, datetime.min.time()).timestamp() * 1000)
    dt = DayText(newest, text, len(text), False, start, True, across=True)
    return {"answer": provider.ask(dt, question), "sources": retrieval.sources(passages),
            "days": len({p.day for p in passages})}
