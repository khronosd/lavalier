"""Ollama on this Mac, over its local HTTP API with urllib only."""

import http.client
import json
import os
import socket
import urllib.error
import urllib.request
from typing import Optional

from lavalier.insights.prompt import SYSTEM_PROMPT, DayText, ask_messages, estimate_tokens, summarize_messages
from lavalier.insights.providers.base import ModelInfo, ProviderCheck, ProviderError
from lavalier.insights.schema import INSIGHT_SCHEMA

DEFAULT_URL = "http://127.0.0.1:11434"
NOT_RUNNING = "Ollama is not running on this Mac. Install it from ollama.com and run it, then press Test."
FREE = "free, runs on this Mac"

# Checked 2026-10-24 against https://ollama.com/library : qwen3 offers 8b, 14b and 30b tags
# (also 0.6b, 1.7b, 4b, 32b, 235b). (memory_gb upper bound, model id); None means no upper bound.
SIZE_CLASSES = ((16, "qwen3:8b"), (32, "qwen3:14b"), (None, "qwen3:30b"))

_CTX_SIZES = (8192, 16384, 32768)
_REPLY_ROOM = 2048
CHECK_TIMEOUT_S = 10


def recommended_model(memory_gb: float) -> str:
    for limit, model in SIZE_CLASSES:
        if limit is None or memory_gb <= limit:
            return model
    raise ValueError("SIZE_CLASSES must end with an unbounded class")


def num_ctx(chars: int) -> int:
    need = estimate_tokens(chars) + _REPLY_ROOM
    return next((n for n in _CTX_SIZES if need <= n), _CTX_SIZES[-1])


def _machine_memory_gb() -> float:
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30


def _is_timeout(e: BaseException) -> bool:
    return isinstance(e, (socket.timeout, TimeoutError)) or (
        isinstance(e, urllib.error.URLError) and isinstance(e.reason, (socket.timeout, TimeoutError)))


class Ollama:
    name = "ollama"

    def __init__(self, model: str, *, url: str = DEFAULT_URL, timeout_s: float = 300,
                 memory_gb: Optional[float] = None, opener=None):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.memory_gb = _machine_memory_gb() if memory_gb is None else memory_gb
        self._open = opener or urllib.request.urlopen

    def _call(self, path: str, body: Optional[dict] = None, timeout_s: Optional[float] = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"},
                                     method="GET" if body is None else "POST")
        try:
            with self._open(req, timeout=self.timeout_s if timeout_s is None else timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                excerpt = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                excerpt = ""
            finally:
                e.close()
            raise ProviderError(f"Ollama answered {e.code}: {excerpt}") from None
        except (urllib.error.URLError, OSError) as e:
            reason = e.reason if isinstance(e, urllib.error.URLError) else e
            if _is_timeout(e):
                raise ProviderError("Ollama took too long to answer") from None
            if isinstance(reason, ConnectionRefusedError):
                raise ProviderError(NOT_RUNNING) from None
            raise ProviderError(f"Could not reach Ollama: {reason}") from None
        except http.client.HTTPException:
            raise ProviderError("Ollama sent a broken reply") from None
        except ValueError:  # includes UnicodeDecodeError and bad JSON
            raise ProviderError("Ollama sent a reply that could not be read") from None

    def _chat(self, messages: list[dict], dt: DayText, schema: Optional[dict]) -> str:
        body = {"model": self.model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                "stream": False, "options": {"num_ctx": num_ctx(dt.chars), "temperature": 0.2}}
        if schema is not None:
            body["format"] = schema
        reply = self._call("/api/chat", body)
        try:
            content = reply["message"]["content"]
        except (KeyError, TypeError):
            raise ProviderError("Ollama sent a reply that could not be read") from None
        if not isinstance(content, str):
            raise ProviderError("Ollama sent a reply that could not be read")
        return content

    def summarize(self, dt: DayText) -> dict:
        content = self._chat(summarize_messages(dt), dt, INSIGHT_SCHEMA)
        try:
            return json.loads(content)
        except ValueError:
            raise ProviderError("The model did not reply with JSON") from None

    def ask(self, dt: DayText, question: str) -> str:
        return self._chat(ask_messages(dt, question), dt, None)

    def check(self) -> ProviderCheck:
        try:
            names = [m["name"] for m in self._call("/api/tags", timeout_s=CHECK_TIMEOUT_S)["models"]]
        except ProviderError as e:
            return ProviderCheck(False, str(e), [])
        except Exception as e:  # check never raises
            return ProviderCheck(False, f"Could not reach Ollama: {type(e).__name__}", [])
        rec = recommended_model(self.memory_gb)
        models = [ModelInfo(n, n, n == rec, FREE) for n in names]
        if self.model not in names:
            return ProviderCheck(False, f"Pull {self.model} in Ollama first", models)
        return ProviderCheck(True, f"Ollama is running with {len(models)} model(s)", models)

    def facts(self) -> dict:
        return {"sends": "each day's transcript text and your questions",
                "to": "Ollama on this Mac; nothing leaves the machine", "cost": FREE}
