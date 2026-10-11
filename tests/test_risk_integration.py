"""Integration tests for risk rule v1 flags against PostgreSQL."""

from __future__ import annotations

from datetime import date

import pytest

from etl.db import connect_owner
from etl.risk import (
    RULE_VERSION,
    build_flag_rows,
    compute_mode_late_rates,
    evaluation_orders,
    predict_orders,
    training_orders,
)
from etl.risk_db import fetch_flags_as_of, load_orders_frame, write_flags

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def require_db(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL is not available")


def _all_flags(conn) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT order_id, flag_date, rule_version, reason
            FROM risk_flags WHERE rule_version = %s
            ORDER BY order_id
            """,
            (RULE_VERSION,),
        )
        return cur.fetchall()


@pytest.mark.real_data
def test_split_counts_add_up() -> None:
    with connect_owner() as conn:
        orders = load_orders_frame(conn)
    assert len(orders) == 8270
    assert len(training_orders(orders)) + len(evaluation_orders(orders)) == 7887


def test_write_flags_is_idempotent_and_matches_predictions() -> None:
    with connect_owner() as conn:
        orders = load_orders_frame(conn)
        rates = compute_mode_late_rates(orders)
        rows = build_flag_rows(orders, rates)
        write_flags(conn, rows)
        first = _all_flags(conn)
        write_flags(conn, rows)
        second = _all_flags(conn)
    assert first == second
    assert len(first) == int(predict_orders(orders, rates).sum())
    excluded_ids = set(orders.loc[orders["is_excluded"], "order_id"])
    assert excluded_ids & {row[0] for row in first}, "excluded orders should be flagged too"


def test_flags_as_of_filters_by_simulated_date() -> None:
    """Flags exist for all dates; "as of now" readers must filter by the clock date."""
    as_of = date(2016, 5, 15)
    with connect_owner() as conn:
        visible = fetch_flags_as_of(conn, as_of)
        everything = _all_flags(conn)
    assert visible, "expected some flags before the as-of date"
    assert all(flag_date <= as_of for _, flag_date, _ in visible)
    assert len(visible) == sum(1 for row in everything if row[1] <= as_of)
    assert len(visible) < len(everything)
