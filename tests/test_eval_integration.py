"""Integration: gold SQL reproduces eval/gold.json, and the dry run passes end to end."""

from __future__ import annotations

import pytest

from eval.gold import build_gold, load_gold, load_questions, read_clock_date
from eval.runner import dry_run_provider, run_eval
from scripts.run_eval import DRY_RUN_PRICING, dry_run_config

pytestmark = [pytest.mark.integration, pytest.mark.real_data]


@pytest.fixture
def owner_conn(db_available):
    if not db_available:
        pytest.skip("PostgreSQL not available")
    from etl.db import connect_owner

    with connect_owner() as conn:
        conn.read_only = True
        yield conn


def test_gold_sql_reproduces_committed_gold(owner_conn) -> None:
    questions = load_questions()
    rebuilt = build_gold(owner_conn, questions, read_clock_date(owner_conn))
    assert rebuilt == load_gold()


def test_dry_run_passes_every_question(owner_conn) -> None:
    """Scripted answers with real read-only tools: every check, including no-leak, passes."""
    questions = load_questions()
    run = run_eval(questions, load_gold(), provider_for=dry_run_provider,
                   config=dry_run_config(), pricing=DRY_RUN_PRICING, max_cost_usd=0.01)
    failed = {r["id"]: [c for c in r["checks"] if not c["passed"]]
              for r in run.results if not r["passed"]}
    assert not run.aborted and failed == {}
    assert len(run.results) == 30
