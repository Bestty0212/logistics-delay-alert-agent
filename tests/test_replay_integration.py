"""Integration tests for event replay against PostgreSQL."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg.errors
import pytest

from etl.db import connect_agent_ro, connect_owner
from etl.replay import ReplayNotStartedError, require_clock_date

pytestmark = pytest.mark.integration

EXPECTED_ORDER_PLACED = 8270
EXPECTED_SLA_DUE = 7887
EXPECTED_ORDER_COMPLETED = 7887
EXPECTED_OVERDUE = 4551
EXPECTED_EXCLUDED_ORDERS = 383
FULL_REPLAY_TO = date(2016, 8, 31)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "db" / "schema.sql"
MIGRATION_PATH = ROOT / "db" / "migrations" / "001_simulation_and_overdue.sql"


@pytest.fixture(scope="module", autouse=True)
def require_db(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL is not available")


def _event_counts(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type")
        return {row[0]: row[1] for row in cur.fetchall()}


def _overdue_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM overdue_alerts")
        return cur.fetchone()[0]


def test_fresh_rebuild_schema_and_migration_define_same_new_objects() -> None:
    """Fresh path uses schema.sql; existing DBs use the additive migration."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    for name in ("simulation_clock", "overdue_alerts"):
        assert name in schema
        assert name in migration
    assert "CHECK (id = 1)" in schema
    assert "docker compose down -v" in migration
    assert "GRANT SELECT ON TABLE simulation_clock TO agent_ro" in migration
    assert "GRANT SELECT ON TABLE overdue_alerts TO agent_ro" in migration


@pytest.mark.real_data
def test_full_replay_counts(db_available: bool) -> None:
    from scripts.replay_events import main

    assert main(["--reset", "--to", FULL_REPLAY_TO.isoformat()]) == 0
    with connect_owner() as conn:
        counts = _event_counts(conn)
        overdue = _overdue_count(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM orders
                WHERE NOT is_excluded AND late_label = TRUE
                """
            )
            late_true = cur.fetchone()[0]
    assert counts.get("order_placed") == EXPECTED_ORDER_PLACED
    assert counts.get("sla_due") == EXPECTED_SLA_DUE
    assert counts.get("order_completed") == EXPECTED_ORDER_COMPLETED
    assert overdue == EXPECTED_OVERDUE
    assert overdue == late_true


@pytest.mark.real_data
def test_excluded_orders_have_exactly_one_event() -> None:
    with connect_owner() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.order_id, COUNT(e.event_id) AS n,
                       COUNT(*) FILTER (WHERE e.event_type = 'order_placed') AS placed
                FROM orders o
                LEFT JOIN events e ON e.order_id = o.order_id
                WHERE o.is_excluded
                GROUP BY o.order_id
                """
            )
            rows = cur.fetchall()
    assert len(rows) == EXPECTED_EXCLUDED_ORDERS
    assert all(n == 1 and placed == 1 for _, n, placed in rows)


def test_replaying_twice_gives_identical_counts() -> None:
    from scripts.replay_events import main

    with connect_owner() as conn:
        before_events = _event_counts(conn)
        before_overdue = _overdue_count(conn)
    assert main(["--to", FULL_REPLAY_TO.isoformat()]) == 0
    with connect_owner() as conn:
        after_events = _event_counts(conn)
        after_overdue = _overdue_count(conn)
    assert after_events == before_events
    assert after_overdue == before_overdue


def test_missing_clock_is_replay_not_started_error() -> None:
    """No clock row => explicit error for readers; never use the real date."""
    with pytest.raises(ReplayNotStartedError, match="replay not started"):
        require_clock_date(None)


@pytest.mark.real_data
def test_agent_ro_select_only_on_new_objects() -> None:
    tables = ("simulation_clock", "overdue_alerts")
    with connect_owner() as conn:
        with conn.cursor() as cur:
            for table in tables:
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    cur.execute(
                        "SELECT has_table_privilege('agent_ro', %s, %s)",
                        (table, privilege),
                    )
                    assert cur.fetchone()[0] is False
                cur.execute(
                    "SELECT has_table_privilege('agent_ro', %s, 'SELECT')",
                    (table,),
                )
                assert cur.fetchone()[0] is True

    with connect_agent_ro() as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM overdue_alerts")
                assert cur.fetchone()[0] == EXPECTED_OVERDUE
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cur.execute(
                        """
                        INSERT INTO overdue_alerts (order_id, alert_date)
                        VALUES (
                            (SELECT order_id FROM orders LIMIT 1),
                            DATE '2016-01-01'
                        )
                        """
                    )
        finally:
            conn.rollback()
