"""A scripted insights provider for the app, server and CLI tests: no network, optional gate."""

import threading
from typing import Optional

from lavalier.insights.providers.base import ProviderCheck, ProviderError

REPLY = {
    "summary": "A short pendant test: two rounds of counting to three, both starred.",
    "follow_ups": [{"text": "Check that both stars landed", "time": "22:56:13"}],
    "people": ["Remy"],
    "topics": ["pendant test"],
}


class FakeProvider:
    """`gate`, when given, holds summarize/ask until it is set, so a test can see a job running."""

    def __init__(self, reply=None, *, error: Optional[str] = None, answer: str = "An answer.",
                 name: str = "ollama", model: str = "fake-model", gate: Optional[threading.Event] = None):
        self.name, self.model = name, model
        self.reply = REPLY if reply is None else reply
        self.error, self.answer, self.gate = error, answer, gate
        self.calls: list[tuple] = []
        self.texts: list = []  # the DayText of each summarize or ask, in order
        self.checks = 0

    def _wait(self):
        if self.gate is not None:
            assert self.gate.wait(10), "the test never opened the gate"

    def summarize(self, dt):
        self.calls.append(("summarize", dt.day))
        self._wait()
        if self.error is not None:
            raise ProviderError(self.error)
        return self.reply

    def ask(self, dt, question):
        self.calls.append(("ask", dt.day, question))
        self.texts.append(dt)
        self._wait()
        if self.error is not None:
            raise ProviderError(self.error)
        return self.answer

    def check(self):
        self.checks += 1
        return ProviderCheck(True, "ok", [])

    def facts(self):
        return {"sends": "text", "to": "this Mac", "cost": "free, runs on this Mac"}
