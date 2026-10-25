"""Anthropic's Claude models, through the official SDK (streaming, structured replies)."""

import json
from typing import Optional

from lavalier.insights.prompt import SYSTEM_PROMPT, DayText, ask_messages, summarize_messages, system_prompt
from lavalier.insights.providers.base import ModelInfo, ProviderCheck, ProviderError
from lavalier.insights.schema import INSIGHT_SCHEMA

MODELS = (
    ModelInfo("claude-opus-5-5", "Claude Opus 5.5", recommended=True, cost_per_day="about $0.20 per 3-hour day"),
    ModelInfo("claude-sonnet-5-5", "Claude Sonnet 5.5", cost_per_day="about $0.10 per 3-hour day"),
    ModelInfo("claude-haiku-5-5", "Claude Haiku 5.5", cost_per_day="about $0.005 per 3-hour day"),
)
DEFAULT_MODEL = "claude-opus-5-5"
NO_KEY = "No key saved. Add one in Settings › Model."
UNKNOWN_COST = "about $0.20 per 3-hour day"

_EFFORT = "medium"  # thinking stays on for Opus 5.5; effort is the only depth control, never `thinking`


def _safe_text(e: BaseException) -> str:
    """Text safe to show the owner for an SDK or transport failure; never the key, never the day's text."""
    import anthropic as sdk

    if isinstance(e, sdk.AuthenticationError):
        return "The key was refused"
    if isinstance(e, sdk.RateLimitError):
        return "Anthropic is rate-limiting; try again in a minute"
    if isinstance(e, sdk.APIStatusError) and e.status_code == 529:
        return "Anthropic is overloaded; try again later"
    if isinstance(e, sdk.APITimeoutError):
        return "Anthropic took too long to answer"
    if isinstance(e, sdk.APIConnectionError):
        return f"Could not reach Anthropic: {type(e).__name__}"
    if isinstance(e, sdk.APIError):
        return str(e)
    return f"Could not reach Anthropic: {type(e).__name__}"


class Anthropic:
    name = "anthropic"

    def __init__(self, model: str, api_key: Optional[str], *, client=None, timeout_s: float = 120):
        self.model = model
        self._client = client
        if client is None and api_key:
            import anthropic as sdk

            self._client = sdk.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)

    def _final(self, max_tokens: int, messages: list[dict], output_config: dict, system: str = SYSTEM_PROMPT):
        if self._client is None:
            raise ProviderError(NO_KEY)
        try:
            with self._client.messages.stream(model=self.model, max_tokens=max_tokens, system=system,
                                              messages=messages, output_config=output_config) as s:
                msg = s.get_final_message()
        except Exception as e:
            raise ProviderError(_safe_text(e)) from None
        if msg.stop_reason == "refusal":
            raise ProviderError("The model declined to summarise this day")
        if msg.stop_reason == "max_tokens":
            raise ProviderError("The reply was cut off")
        return [b.text for b in msg.content if getattr(b, "type", None) == "text"]

    def summarize(self, dt: DayText) -> dict:
        texts = self._final(4096, summarize_messages(dt),
                            {"format": {"type": "json_schema", "schema": INSIGHT_SCHEMA}, "effort": _EFFORT})
        try:
            out = json.loads(texts[0]) if texts else None
        except ValueError:
            out = None
        if not isinstance(out, dict):
            raise ProviderError("The model did not reply with JSON")
        return out

    def ask(self, dt: DayText, question: str) -> str:
        answer = "".join(self._final(2048, ask_messages(dt, question), {"effort": _EFFORT}, system_prompt(dt)))
        if not answer.strip():
            raise ProviderError("The model gave no answer")
        return answer

    def check(self) -> ProviderCheck:
        if self._client is None:
            return ProviderCheck(False, NO_KEY, MODELS)
        try:
            self._client.models.retrieve(self.model)
        except Exception as e:  # check never raises
            try:
                detail = _safe_text(e)
            except Exception:
                detail = f"Could not reach Anthropic: {type(e).__name__}"
            return ProviderCheck(False, detail, MODELS)
        return ProviderCheck(True, f"Anthropic answered; {self.model} is available", MODELS)

    def facts(self) -> dict:
        cost = next((m.cost_per_day for m in MODELS if m.id == self.model), None) or UNKNOWN_COST
        return {"sends": "each day's transcript text and your questions, never audio", "to": "Anthropic",
                "cost": cost}
