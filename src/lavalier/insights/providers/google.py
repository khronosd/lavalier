"""Google's Gemini models, through the official google-genai SDK."""

import json
from typing import Optional

from lavalier.insights.prompt import SYSTEM_PROMPT, DayText, ask_messages, summarize_messages, system_prompt
from lavalier.insights.providers.base import ModelInfo, ProviderCheck, ProviderError
from lavalier.insights.schema import INSIGHT_SCHEMA

# Looked up 2026-10-24: https://ai.google.dev/gemini-api/docs/pricing (paid tier, per 1M tokens, in/out):
# gemini-3.8-flash $0.75/$3.75 (rises to $1.50/$7.50 on 2027-01-01), gemini-4-argon $2/$10 (rises to $4/$20 on
# 2026-12-01), gemini-3.5-flash-lite $0.30/$2.50. The costs below are today's prices. cost_per_day = 40k input +
# 1.5k output tokens, two significant figures.
# SDK checked 2026-10-24 against google-genai 2.33 (types and docstrings): genai.Client(api_key=, http_options=
# {"timeout": <ms>}), models.generate_content(model=, contents=, config=<GenerateContentConfig or dict>),
# response.text, models.get(model=), errors.APIError/ClientError/ServerError (.code, .message). The config field
# for a JSON-schema dict is `response_json_schema` (`response_schema` wants the OpenAPI-subset types.Schema).
MODELS = (
    ModelInfo("gemini-3.8-flash", "Gemini 3.8 Flash", recommended=True, cost_per_day="about $0.036 per 3-hour day"),
    ModelInfo("gemini-4-argon", "Gemini 4 Argon", cost_per_day="about $0.095 per 3-hour day"),
    ModelInfo("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", cost_per_day="about $0.016 per 3-hour day"),
)
DEFAULT_MODEL = "gemini-3.8-flash"
NO_KEY = "No key saved. Add one in Settings › Model."
UNKNOWN_COST = "about $0.036 per 3-hour day"
NO_ANSWER = "The model gave no answer"


def _safe_text(e: BaseException) -> str:
    """Text safe to show the owner for an SDK or transport failure; never the key, never the day's text."""
    from google.genai import errors

    if isinstance(e, errors.APIError):
        message = str(getattr(e, "message", "") or "")
        if e.code in (401, 403) or "api key not valid" in message.lower():
            return "The key was refused"
        if e.code == 429:
            return "Google is rate-limiting; try again in a minute"
        if isinstance(e.code, int) and e.code >= 500:
            return "Google is unavailable; try again later"
        return message or f"Google answered {e.code}"
    name = type(e).__name__
    if isinstance(e, TimeoutError) or "Timeout" in name:
        return "Google took too long to answer"
    if isinstance(e, OSError) or type(e).__module__.split(".")[0] in ("httpx", "httpx2"):
        return "Could not reach Google"
    return f"Could not reach Google: {name}"


class Google:
    name = "google"

    def __init__(self, model: str, api_key: Optional[str], *, client=None, timeout_s: float = 120):
        self.model = model
        self._client = client
        if client is None and api_key:
            import google.genai as sdk

            self._client = sdk.Client(api_key=api_key, http_options={"timeout": int(timeout_s * 1000)})

    def _text(self, user_text: str, extra: dict, system: str = SYSTEM_PROMPT) -> str:
        if self._client is None:
            raise ProviderError(NO_KEY)
        config = {"system_instruction": system, **extra, "temperature": 0.2}
        try:
            return self._client.models.generate_content(model=self.model, contents=user_text, config=config).text or ""
        except Exception as e:
            raise ProviderError(_safe_text(e)) from None

    def summarize(self, dt: DayText) -> dict:
        reply = self._text(summarize_messages(dt)[0]["content"],
                           {"response_mime_type": "application/json", "response_json_schema": INSIGHT_SCHEMA})
        try:
            out = json.loads(reply)
        except ValueError:
            out = None
        if not isinstance(out, dict):
            raise ProviderError("The model did not reply with JSON")
        return out

    def ask(self, dt: DayText, question: str) -> str:
        answer = self._text(ask_messages(dt, question)[0]["content"], {}, system_prompt(dt))
        if not answer.strip():
            raise ProviderError(NO_ANSWER)
        return answer

    def check(self) -> ProviderCheck:
        if self._client is None:
            return ProviderCheck(False, NO_KEY, MODELS)
        try:
            self._client.models.get(model=self.model)
        except Exception as e:  # check never raises
            try:
                detail = _safe_text(e)
            except Exception:
                detail = f"Could not reach Google: {type(e).__name__}"
            return ProviderCheck(False, detail, MODELS)
        return ProviderCheck(True, f"Google answered; {self.model} is available", MODELS)

    def facts(self) -> dict:
        cost = next((m.cost_per_day for m in MODELS if m.id == self.model), None) or UNKNOWN_COST
        return {"sends": "each day's transcript text and your questions, never audio", "to": "Google", "cost": cost}
