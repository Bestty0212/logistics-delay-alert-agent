"""Single-order lookup and status shared by the timeline and draft tools."""

from __future__ import annotations

from datetime import date

import psycopg

from agent_tools.db import fetch_one
from agent_tools.results import ORDER_NOT_FOUND, ToolError
from etl.risk import RULE_VERSION

ORDER_NOT_FOUND_MESSAGE = "order not found as of that date"
NO_UPDATES_MESSAGE = "No further updates are available for this order."


def fetch_visible_order(conn: psycopg.Connection, order_id: int, as_of: date) -> dict:
    """Order known at as_of (order_date <= as_of); completion hidden until completed_on."""
    row = fetch_one(
        conn,
        """
        SELECT o.order_id, o.order_date, o.shipping_mode, s.english_name AS state,
               o.sla_due_on, o.completed_on, o.is_excluded,
               EXISTS (
                   SELECT 1 FROM risk_flags f
                   WHERE f.order_id = o.order_id
                     AND f.rule_version = %(rule_version)s
                     AND f.flag_date <= %(as_of)s
               ) AS at_risk
        FROM orders o
        JOIN state_names s ON s.original_name = o.order_state
        WHERE o.order_id = %(order_id)s AND o.order_date <= %(as_of)s
        """,
        {"order_id": order_id, "as_of": as_of, "rule_version": RULE_VERSION},
    )
    if row is None:
        raise ToolError(ORDER_NOT_FOUND, ORDER_NOT_FOUND_MESSAGE)
    if row["completed_on"] is not None and row["completed_on"] > as_of:
        row["completed_on"] = None
    return row


def order_status(order: dict, as_of: date) -> str:
    """completed_on_time | completed_late | overdue | open | no_updates.

    Expects completed_on already hidden when it is after as_of. Overdue means the
    promised date is on or before as_of with no visible completion (the replay
    raises the overdue alert at the end of the due day).
    """
    if order["is_excluded"]:
        return "no_updates"
    completed_on = order["completed_on"]
    if completed_on is not None:
        return "completed_late" if completed_on > order["sla_due_on"] else "completed_on_time"
    if order["sla_due_on"] <= as_of:
        return "overdue"
    return "open"
