"""Database access for risk rule v1: load orders, write flags, read flags as of a date."""

from __future__ import annotations

from datetime import date

import pandas as pd
import psycopg

from etl.risk import RULE_VERSION

ORDER_COLUMNS = [
    "order_id",
    "order_date",
    "shipping_mode",
    "scheduled_days",
    "order_state",
    "payment_type",
    "is_excluded",
    "late_label",
    "department_names",
]


def load_orders_frame(conn: psycopg.Connection) -> pd.DataFrame:
    """Orders with order-time features, evaluation fields, and their departments."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT o.order_id, o.order_date, o.shipping_mode, o.scheduled_days,
                   o.order_state, o.payment_type, o.is_excluded, o.late_label,
                   ARRAY_AGG(DISTINCT oi.department_name ORDER BY oi.department_name)
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            GROUP BY o.order_id
            ORDER BY o.order_id
            """
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=ORDER_COLUMNS)


def write_flags(
    conn: psycopg.Connection,
    rows: list[tuple[int, date, str]],
    rule_version: str = RULE_VERSION,
) -> None:
    """Replace all flags for rule_version in one transaction (idempotent)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM risk_flags WHERE rule_version = %s", (rule_version,))
        cur.executemany(
            """
            INSERT INTO risk_flags (order_id, flag_date, rule_version, reason)
            VALUES (%s, %s, %s, %s)
            """,
            [(order_id, flag_date, rule_version, reason) for order_id, flag_date, reason in rows],
        )
    conn.commit()


def fetch_flags_as_of(
    conn: psycopg.Connection, as_of: date, rule_version: str = RULE_VERSION
) -> list[tuple[int, date, str]]:
    """Flags visible "as of now": flag_date <= as_of.

    Flags exist for all dates at once, so readers must always pass the simulated
    clock date (see etl.replay.require_clock_date), never the real date.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT order_id, flag_date, reason
            FROM risk_flags
            WHERE rule_version = %s AND flag_date <= %s
            ORDER BY flag_date, order_id
            """,
            (rule_version, as_of),
        )
        return cur.fetchall()
