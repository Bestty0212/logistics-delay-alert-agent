"""draft_notification: deterministic customer draft for one order; never sent."""

from __future__ import annotations

from datetime import date

import psycopg

from agent_tools.db import run_tool
from agent_tools.orders import fetch_visible_order, order_status
from agent_tools.validation import parse_order_id

NOT_AVAILABLE_MESSAGE = "A notification draft is not available for this order."
NOT_NEEDED_MESSAGE = "No notification is needed for this order as of this date."

OVERDUE_TEMPLATE = (
    "Hello, we are sorry: your order {order_id}, shipped with {shipping_mode}, "
    "was planned for {promised_date} and is taking longer than planned. "
    "We are looking into it and will update you as soon as we can. "
    "Thank you for your patience."
)
AT_RISK_TEMPLATE = (
    "Hello, this is a heads-up about your order {order_id}, shipped with "
    "{shipping_mode} and planned for {promised_date}. Delivery may take longer "
    "than planned. We will keep you informed. Thank you for your patience."
)
TEMPLATES = {"overdue": OVERDUE_TEMPLATE, "at_risk": AT_RISK_TEMPLATE}


def choose_variant(status: str, at_risk: bool) -> str | None:
    """Overdue takes precedence over at-risk; completed or on-track orders get none."""
    if status == "overdue":
        return "overdue"
    if status == "open" and at_risk:
        return "at_risk"
    return None


def render_draft(variant: str, order_id: int, promised_date: date, shipping_mode: str) -> str:
    return TEMPLATES[variant].format(
        order_id=order_id,
        shipping_mode=shipping_mode,
        promised_date=promised_date.isoformat(),
    )


def _no_draft(order_id: int, message: str) -> dict:
    return {"draft": None, "sent": False, "message": message, "facts_used": {"order_id": order_id}}


def _draft(conn: psycopg.Connection, as_of: date, args: dict) -> dict:
    order = fetch_visible_order(conn, args["order_id"], as_of)
    status = order_status(order, as_of)
    if status == "no_updates":
        return _no_draft(order["order_id"], NOT_AVAILABLE_MESSAGE)
    variant = choose_variant(status, bool(order["at_risk"]))
    if variant is None:
        return _no_draft(order["order_id"], NOT_NEEDED_MESSAGE)
    return {
        "draft": render_draft(
            variant, order["order_id"], order["sla_due_on"], order["shipping_mode"]
        ),
        "sent": False,
        "facts_used": {
            "order_id": order["order_id"],
            "promised_date": order["sla_due_on"].isoformat(),
            "shipping_mode": order["shipping_mode"],
            "variant": variant,
        },
    }


def draft_notification(order_id: object, as_of: object = None) -> dict:
    return run_tool(as_of, lambda: {"order_id": parse_order_id(order_id)}, _draft)
