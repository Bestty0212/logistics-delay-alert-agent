"""Integration tests against PostgreSQL (owner + agent_ro)."""

from __future__ import annotations

import psycopg.errors
import pytest

from etl.db import connect_agent_ro, connect_owner
from etl.transforms import DROPPED_COLUMN_NAMES

pytestmark = pytest.mark.integration

EXPECTED_ITEMS = 24840
EXPECTED_ORDERS = 8270
EXPECTED_EXCLUDED = 1120
EXPECTED_NON_EXCLUDED = 23720


@pytest.fixture(scope="module", autouse=True)
def require_db(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL is not available")


@pytest.mark.real_data
def test_imported_counts() -> None:
    with connect_owner() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM order_items")
            items = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM orders")
            orders = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*) FROM order_items oi
                JOIN orders o ON o.order_id = oi.order_id
                WHERE o.is_excluded
                """
            )
            excluded = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*) FROM order_items oi
                JOIN orders o ON o.order_id = oi.order_id
                WHERE NOT o.is_excluded
                """
            )
            non_excluded = cur.fetchone()[0]

    assert items == EXPECTED_ITEMS
    assert orders == EXPECTED_ORDERS
    assert excluded == EXPECTED_EXCLUDED
    assert non_excluded == EXPECTED_NON_EXCLUDED


def test_no_dropped_columns_exist_in_any_table() -> None:
    with connect_owner() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                """
            )
            columns = {(t, c) for t, c in cur.fetchall()}
            all_names = {c for _, c in columns}

    for dropped in DROPPED_COLUMN_NAMES:
        snake = dropped.lower().replace(" ", "_")
        assert dropped not in all_names
        assert snake not in all_names
        # also reject common privacy-ish names
        assert "email" not in all_names
        assert "password" not in all_names
        assert "fname" not in all_names
        assert "lname" not in all_names
        assert "zipcode" not in all_names


def test_all_order_states_mapped() -> None:
    with connect_owner() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM orders o
                LEFT JOIN state_names s ON s.original_name = o.order_state
                WHERE s.original_name IS NULL
                """
            )
            unmapped = cur.fetchone()[0]
    assert unmapped == 0


@pytest.mark.real_data
def test_real_dataset_has_48_states() -> None:
    with connect_owner() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM state_names")
            assert cur.fetchone()[0] == 48


def test_date_columns_are_date_type() -> None:
    date_columns = {
        ("orders", "order_date"),
        ("orders", "completed_on"),
        ("orders", "sla_due_on"),
        ("events", "event_date"),
        ("risk_flags", "flag_date"),
    }
    with connect_owner() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND (table_name, column_name) IN (
                    ('orders', 'order_date'),
                    ('orders', 'completed_on'),
                    ('orders', 'sla_due_on'),
                    ('events', 'event_date'),
                    ('risk_flags', 'flag_date')
                  )
                """
            )
            found = {(t, c): dtype for t, c, dtype in cur.fetchall()}
    assert set(found) == date_columns
    assert all(dtype == "date" for dtype in found.values())


def test_excluded_orders_null_completed_on_and_late_label() -> None:
    with connect_owner() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM orders
                WHERE is_excluded
                  AND (completed_on IS NOT NULL OR late_label IS NOT NULL)
                """
            )
            bad_excluded = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*) FROM orders
                WHERE NOT is_excluded
                  AND (completed_on IS NULL OR late_label IS NULL)
                """
            )
            bad_active = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*) FROM orders
                WHERE is_excluded
                  AND completed_on IS NULL
                  AND late_label IS NULL
                """
            )
            good_excluded = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM orders WHERE is_excluded")
            excluded_orders = cur.fetchone()[0]
    assert bad_excluded == 0
    assert bad_active == 0
    assert good_excluded == excluded_orders


@pytest.mark.real_data
def test_agent_ro_can_select() -> None:
    with connect_agent_ro() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orders")
            assert cur.fetchone()[0] == EXPECTED_ORDERS


def test_agent_ro_cannot_insert_update_delete_or_create() -> None:
    tables = ("orders", "order_items", "events", "risk_flags", "state_names")

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
            cur.execute("SELECT has_schema_privilege('agent_ro', 'public', 'CREATE')")
            assert cur.fetchone()[0] is False

    with connect_agent_ro() as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cur.execute(
                        """
                        INSERT INTO state_names (original_name, english_name)
                        VALUES ('Testland', 'Testland')
                        """
                    )
        finally:
            conn.rollback()
