"""list_at_risk_orders: flagged, open orders as of a date, by promised date."""

from __future__ import annotations

from datetime import date

import psycopg

from agent_tools.db import fetch_all, fetch_one, resolve_state, run_tool
from agent_tools.validation import parse_limit, parse_state
from etl.risk import RULE_VERSION

_OPEN_AT_RISK_FROM = """
    FROM orders o
    JOIN risk_flags f
      ON f.order_id = o.order_id AND f.rule_version = %(rule_version)s
    JOIN state_names s ON s.original_name = o.order_state
    WHERE f.flag_date <= %(as_of)s
      AND o.order_date <= %(as_of)s
      AND NOT o.is_excluded
      AND NOT (o.completed_on <= %(as_of)s)
      AND (%(state)s::text IS NULL OR o.order_state = %(state)s)
"""


def _query_params(as_of: date, state: str | None, limit: int | None = None) -> dict:
    return {"as_of": as_of, "state": state, "rule_version": RULE_VERSION, "limit": limit}


def count_open_at_risk(conn: psycopg.Connection, as_of: date, state: str | None) -> int:
    row = fetch_one(conn, "SELECT COUNT(*) AS n" + _OPEN_AT_RISK_FROM, _query_params(as_of, state))
    return row["n"]


def fetch_open_at_risk(
    conn: psycopg.Connection, as_of: date, state: str | None, limit: int
) -> list[dict]:
    return fetch_all(
        conn,
        """
        SELECT o.order_id, o.order_date, o.sla_due_on, o.shipping_mode,
               s.english_name AS state, (o.sla_due_on <= %(as_of)s) AS overdue
        """
        + _OPEN_AT_RISK_FROM
        + " ORDER BY o.sla_due_on, o.order_id LIMIT %(limit)s",
        _query_params(as_of, state, limit),
    )


def _list(conn: psycopg.Connection, as_of: date, args: dict) -> dict:
    state = resolve_state(conn, args["state"])
    rows = fetch_open_at_risk(conn, as_of, state, args["limit"])
    total = count_open_at_risk(conn, as_of, state)
    return {
        "orders": [
            {
                "order_id": r["order_id"],
                "order_date": r["order_date"].isoformat(),
                "promised_date": r["sla_due_on"].isoformat(),
                "shipping_mode": r["shipping_mode"],
                "state": r["state"],
                "overdue": bool(r["overdue"]),
            }
            for r in rows
        ],
        "returned": len(rows),
        "total_matching": total,
        "truncated": total > len(rows),
    }


def list_at_risk_orders(state: object = None, as_of: object = None, limit: object = None) -> dict:
    return run_tool(
        as_of,
        lambda: {"state": parse_state(state), "limit": parse_limit(limit)},
        _list,
    )
