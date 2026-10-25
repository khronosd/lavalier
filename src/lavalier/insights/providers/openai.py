"""OpenAI's models, or any OpenAI-compatible endpoint, through the official SDK (Responses API)."""

import json
from typing import Optional

from lavalier.insights.prompt import SYSTEM_PROMPT, DayText, ask_messages, summarize_messages, system_prompt
from lavalier.insights.providers.base import ModelInfo, ProviderCheck, ProviderError
from lavalier.insights.schema import INSIGHT_SCHEMA

# Looked up 2026-10-24: https://developers.openai.com/api/docs/pricing (standard tier, per 1M tokens, in/out):
# gpt-6.1-sol $2/$10, gpt-6-astra $10/$50, gpt-6-luna $0.10/$0.50. The page does not name a flagship; the default is
# the newest general model at a mid price. cost_per_day = 40k input + 1.5k output tokens, two significant figures.
# SDK checked 2026-10-24 against openai 3.37 (docstrings and type stubs): responses.create(model, instructions,
# input, text=), Response.output_text, models.retrieve(model), models.list(), and the exception classes
# AuthenticationError, RateLimitError, APITimeoutError (a subclass of APIConnectionError), APIConnectionError,
# APIStatusError, InternalServerError.
MODELS = (
    ModelInfo("gpt-6.1-sol", "GPT-6.1 Sol", recommended=True, cost_per_day="about $0.095 per 3-hour day"),
    ModelInfo("gpt-6-astra", "GPT-6 Astra", cost_per_day="about $0.48 per 3-hour day"),
    ModelInfo("gpt-6-luna", "GPT-6 Luna", cost_per_day="about $0.0048 per 3-hour day"),
)
DEFAULT_MODEL = "gpt-6.1-sol"
NO_KEY = "No key saved. Add one in Settings › Model."
UNKNOWN_COST = "about $0.095 per 3-hour day"
ENDPOINT_COST = "set by that endpoint"
NO_ANSWER = "The model gave no answer"

_FORMAT = {"type": "json_schema", "name": "insight", "schema": INSIGHT_SCHEMA, "strict": True}


def _safe_text(e: BaseException) -> str:
    """Text safe to show the owner for an SDK or transport failure; never the key, never the day's text."""
    import openai as sdk

    if isinstance(e, sdk.AuthenticationError):
        return "The key was refused"
    if isinstance(e, sdk.RateLimitError):
        return "OpenAI is rate-limiting; try again in a minute"
    if isinstance(e, sdk.APIStatusError) and e.status_code >= 500:
        return "OpenAI is unavailable; try again later"
    if isinstance(e, sdk.APITimeoutError):
        return "OpenAI took too long to answer"
    if isinstance(e, sdk.APIConnectionError):
        return "Could not reach OpenAI"
    if isinstance(e, sdk.APIError):
        return str(e)
    return f"Could not reach OpenAI: {type(e).__name__}"


class OpenAI:
    name = "openai"

    def __init__(self, model: str, api_key: Optional[str], *, base_url: str = "", client=None,
                 timeout_s: float = 120):
        self.model = model
        self.base_url = base_url
        self._client = client
        if client is None and api_key:
            import openai as sdk

            self._client = sdk.OpenAI(api_key=api_key, base_url=base_url or None, timeout=timeout_s)

    def _text(self, user_text: str, text_format: Optional[dict], system: str = SYSTEM_PROMPT) -> str:
        if self._client is None:
            raise ProviderError(NO_KEY)
        kwargs = {"model": self.model, "instructions": system, "input": user_text}
        if text_format is not None:
            kwargs["text"] = {"format": text_format}
        try:
            return self._client.responses.create(**kwargs).output_text or ""
        except Exception as e:
            raise ProviderError(_safe_text(e)) from None

    def summarize(self, dt: DayText) -> dict:
        reply = self._text(summarize_messages(dt)[0]["content"], _FORMAT)
        try:
            out = json.loads(reply)
        except ValueError:
            out = None
        if not isinstance(out, dict):
            raise ProviderError("The model did not reply with JSON")
        return out

    def ask(self, dt: DayText, question: str) -> str:
        answer = self._text(ask_messages(dt, question)[0]["content"], None, system_prompt(dt))
        if not answer.strip():
            raise ProviderError(NO_ANSWER)
        return answer

    def check(self) -> ProviderCheck:
        shown = [ModelInfo(self.model, self.model)] if self.base_url else MODELS
        if self._client is None:
            return ProviderCheck(False, NO_KEY, shown)
        try:
            self._client.models.retrieve(self.model)
        except Exception as e:  # check never raises
            try:
                detail = _safe_text(e)
            except Exception:
                detail = f"Could not reach OpenAI: {type(e).__name__}"
            return ProviderCheck(False, detail, shown)
        if self.base_url:
            try:
                ids = [str(m.id) for m in self._client.models.list()]
                if ids:
                    shown = [ModelInfo(i, i) for i in ids]
            except Exception:  # the endpoint may not list; show the configured one
                pass
        return ProviderCheck(True, f"OpenAI answered; {self.model} is available", shown)

    def facts(self) -> dict:
        if self.base_url:
            to, cost = f"the endpoint at {self.base_url}", ENDPOINT_COST
        else:
            to = "OpenAI"
            cost = next((m.cost_per_day for m in MODELS if m.id == self.model), None) or UNKNOWN_COST
        return {"sends": "each day's transcript text and your questions, never audio", "to": to, "cost": cost}
