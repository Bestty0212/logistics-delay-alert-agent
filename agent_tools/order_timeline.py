"""get_order_timeline: one order's events and promised date as of a date."""

from __future__ import annotations

from datetime import date

import psycopg

from agent_tools.db import fetch_all, run_tool
from agent_tools.orders import NO_UPDATES_MESSAGE, fetch_visible_order, order_status
from agent_tools.validation import parse_order_id


def fetch_events(conn: psycopg.Connection, order_id: int, as_of: date) -> list[dict]:
    return fetch_all(
        conn,
        """
        SELECT event_type, event_date
        FROM events
        WHERE order_id = %(order_id)s AND event_date <= %(as_of)s
        ORDER BY event_date,
                 CASE event_type
                     WHEN 'order_placed' THEN 1
                     WHEN 'order_completed' THEN 2
                     ELSE 3
                 END
        """,
        {"order_id": order_id, "as_of": as_of},
    )


def _timeline(conn: psycopg.Connection, as_of: date, args: dict) -> dict:
    order = fetch_visible_order(conn, args["order_id"], as_of)
    events = fetch_events(conn, order["order_id"], as_of)
    status = order_status(order, as_of)
    data = {
        "order_id": order["order_id"],
        "order_date": order["order_date"].isoformat(),
        "shipping_mode": order["shipping_mode"],
        "state": order["state"],
        "promised_date": order["sla_due_on"].isoformat(),
        "at_risk": bool(order["at_risk"]),
        "events": [
            {"type": e["event_type"], "date": e["event_date"].isoformat()} for e in events
        ],
        "completed_on": order["completed_on"].isoformat() if order["completed_on"] else None,
        "status": status,
    }
    if status == "no_updates":
        data["message"] = NO_UPDATES_MESSAGE
    return data


def get_order_timeline(order_id: object, as_of: object = None) -> dict:
    return run_tool(as_of, lambda: {"order_id": parse_order_id(order_id)}, _timeline)
