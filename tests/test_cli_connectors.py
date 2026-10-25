import dataclasses
from datetime import date

import pytest

import fake_notion as fn
from conftest import _serve_real_app
from fake_pendant import FakePendant
from lavalier import cli
from lavalier.connectors.export import STOPPED
from lavalier.connectors.notion import NO_TOKEN, Notion
from lavalier.insights import keys
from lavalier.window import NOT_RUNNING

DAY = "2026-10-23"


@pytest.fixture
def served(cli_env, app_env, db, seeded_2026_10_23_subset, memory_keyring, monkeypatch):
    """A real App behind a real server at the CLI's state root, with Notion on and a scripted SDK."""
    monkeypatch.setattr(cli, "JOB_POLL_S", 0.01)
    app = app_env(FakePendant())
    app.cfg = dataclasses.replace(app.cfg, notion_enabled=True, notion_database_id=fn.DATABASE_ID)
    keys.set_key("notion", fn.SECRET)
    app.fake = fn.FakeNotionClient()
    app.notion_factory = lambda token: Notion(token, client=app.fake, sleep=lambda s: None)
    for srv in _serve_real_app(app, db):
        yield srv


def test_cli_export_prints_each_day_and_a_summary(cli_env, served):
    r = cli_env.invoke(["export"])
    assert r.exit_code == 0, r.output
    assert r.output.splitlines() == [f"{DAY}: exported", "Exported 1, unchanged 0, stopped 0, errors 0"]
    r = cli_env.invoke(["export", DAY])
    assert r.exit_code == 0 and r.output.splitlines()[0] == f"{DAY}: unchanged"


def test_cli_export_reports_a_stopped_day_and_force_exports_it(cli_env, served, db):
    assert cli_env.invoke(["export", DAY]).exit_code == 0
    served.app.fake.add_owner_block(db.export(date(2026, 10, 23), "notion").block_id, "mine")
    r = cli_env.invoke(["export", DAY])
    assert r.exit_code == 0 and r.output.splitlines()[0] == f"{DAY}: stopped: {STOPPED}"
    assert "stopped 1" in r.output
    r = cli_env.invoke(["export", DAY, "--force"])
    assert r.exit_code == 0 and r.output.splitlines()[0] == f"{DAY}: exported"


def test_cli_export_prints_a_day_error(cli_env, served):
    r = cli_env.invoke(["export", "2026-10-20"])
    assert r.exit_code == 0 and r.output.splitlines()[0] == "2026-10-20: error: Nothing to export"
    assert "errors 1" in r.output


def test_cli_export_with_days_sends_them(cli_env, served):
    r = cli_env.invoke(["export", "--days", "30"])
    assert r.exit_code == 0 and f"{DAY}: exported" in r.output


def test_cli_export_refused_exits_1_with_the_reason(cli_env, served, memory_keyring):
    served.app._app.cfg = dataclasses.replace(served.app.cfg, notion_enabled=False)
    r = cli_env.invoke(["export"])
    assert r.exit_code == 1 and "off" in r.output
    served.app._app.cfg = dataclasses.replace(served.app.cfg, notion_enabled=True)
    keys.delete_key("notion")
    r = cli_env.invoke(["export", DAY])               # the job finds no token
    assert r.exit_code == 1 and NO_TOKEN in r.output


def test_cli_export_rejects_a_day_with_days(cli_env, served):
    assert cli_env.invoke(["export", DAY, "--days", "3"]).exit_code == 2


def test_cli_export_needs_the_app(cli_env):
    r = cli_env.invoke(["export"])
    assert r.exit_code == 1 and NOT_RUNNING in r.output
