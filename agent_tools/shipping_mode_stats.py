"""get_shipping_mode_stats: late rate by mode over orders completed by as_of."""

from __future__ import annotations

from datetime import date

import psycopg

from agent_tools.db import fetch_all, resolve_state, run_tool
from agent_tools.validation import parse_state

SMALL_SAMPLE_THRESHOLD = 30


def fetch_mode_counts(conn: psycopg.Connection, as_of: date, state: str | None) -> list[dict]:
    """Late = completed after the promised date, using only visible completions."""
    return fetch_all(
        conn,
        """
        SELECT o.shipping_mode,
               COUNT(*) AS completed_orders,
               COUNT(*) FILTER (WHERE o.completed_on > o.sla_due_on) AS late_orders
        FROM orders o
        WHERE NOT o.is_excluded
          AND o.completed_on <= %(as_of)s
          AND (%(state)s::text IS NULL OR o.order_state = %(state)s)
        GROUP BY o.shipping_mode
        ORDER BY o.shipping_mode
        """,
        {"as_of": as_of, "state": state},
    )


def mode_row(shipping_mode: str, completed_orders: int, late_orders: int) -> dict:
    return {
        "shipping_mode": shipping_mode,
        "completed_orders": completed_orders,
        "late_orders": late_orders,
        "late_rate": round(late_orders / completed_orders, 4),
        "small_sample": completed_orders < SMALL_SAMPLE_THRESHOLD,
    }


def _stats(conn: psycopg.Connection, as_of: date, args: dict) -> dict:
    state = resolve_state(conn, args["state"])
    rows = fetch_mode_counts(conn, as_of, state)
    return {
        "modes": [
            mode_row(r["shipping_mode"], r["completed_orders"], r["late_orders"]) for r in rows
        ]
    }


def get_shipping_mode_stats(state: object = None, as_of: object = None) -> dict:
    return run_tool(as_of, lambda: {"state": parse_state(state)}, _stats)
