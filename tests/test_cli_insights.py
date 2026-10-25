import dataclasses
from datetime import datetime

import pytest

from conftest import _serve_real_app
from fake_pendant import FakePendant
from fake_provider import FakeProvider
from lavalier import cli
from lavalier.window import NOT_RUNNING

DAY = "2026-10-23"
AFTER_DAY = int(datetime(2026, 10, 24, 5, 0).timestamp() * 1000)
ENABLED = int(datetime(2026, 10, 23, 12, 0).timestamp() * 1000)


@pytest.fixture
def served(cli_env, app_env, db, seeded_2026_10_23_subset, monkeypatch):
    """A real App behind a real server at the CLI's state root, with a scripted provider."""
    monkeypatch.setattr(cli, "JOB_POLL_S", 0.01)
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, insights_provider="ollama")
    app.fake = FakeProvider()
    app.provider_factory = lambda cfg: app.fake
    for srv in _serve_real_app(app, db):
        yield srv


def test_cli_insights_polls_and_prints_the_summary(cli_env, served):
    r = cli_env.invoke(["insights", DAY])
    assert r.exit_code == 0, r.output
    assert "A short pendant test: two rounds of counting to three, both starred." in r.output
    assert "22:56:13  Check that both stars landed" in r.output
    assert served.app.fake.calls == [("summarize", datetime(2026, 10, 23).date())]


def test_cli_insights_needs_force_to_generate_again(cli_env, served):
    assert cli_env.invoke(["insights", DAY]).exit_code == 0
    r = cli_env.invoke(["insights", DAY])
    assert r.exit_code == 0 and f"Insights for {DAY} exist; use --force to generate again" in r.output
    assert len(served.app.fake.calls) == 1
    r = cli_env.invoke(["insights", DAY, "--force"])
    assert r.exit_code == 0 and len(served.app.fake.calls) == 2


def test_cli_insights_shows_a_failure_and_exits_1(cli_env, served):
    served.app.fake.error = "Ollama is not running on this Mac."
    r = cli_env.invoke(["insights", DAY])
    assert r.exit_code == 1 and "Ollama is not running on this Mac." in r.output


def test_cli_insights_without_a_day_shows_what_auto_would_do(cli_env, served):
    served.app._app._now_ms = lambda: AFTER_DAY
    r = cli_env.invoke(["insights"])
    assert r.exit_code == 0 and "Automatic insights: on (ollama)" in r.output
    assert "Due now: none" in r.output and f"Without insights: {DAY}" in r.output
    served.app.db.set_status("insights_enabled_at_ms", str(ENABLED))
    r = cli_env.invoke(["insights"])
    assert f"Due now: {DAY}" in r.output


def test_cli_ask_prints_the_answer(cli_env, served):
    served.app.fake.answer = "You counted to three twice."
    r = cli_env.invoke(["ask", DAY, "what did I count?"])
    assert r.exit_code == 0 and r.output.strip() == "You counted to three twice."
    assert served.app.fake.calls[-1][2] == "what did I count?"


def test_cli_prints_the_reason_without_a_provider(cli_env, served):
    served.app._app.cfg = dataclasses.replace(served.app.cfg, insights_provider="")
    r = cli_env.invoke(["insights", DAY])
    assert r.exit_code == 1 and "No model chosen." in r.output
    r = cli_env.invoke(["ask", DAY, "who?"])
    assert r.exit_code == 1 and "No model chosen." in r.output


@pytest.mark.parametrize("args", [["insights", DAY], ["insights"], ["ask", DAY, "who?"]])
def test_cli_insights_and_ask_need_the_app(cli_env, args):
    r = cli_env.invoke(args)
    assert r.exit_code == 1 and NOT_RUNNING in r.output
