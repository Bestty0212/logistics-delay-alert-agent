"""Tool specifications (JSON Schema) and a single validated entry point."""

from __future__ import annotations

from collections.abc import Callable

from agent_tools.at_risk_orders import list_at_risk_orders
from agent_tools.draft_notification import draft_notification
from agent_tools.order_timeline import get_order_timeline
from agent_tools.results import INVALID_ARGUMENT, ToolError, error
from agent_tools.shipping_mode_stats import get_shipping_mode_stats
from agent_tools.validation import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_ORDER_ID,
    MAX_STATE_LENGTH,
    check_arguments,
)

_AS_OF = {
    "type": "string",
    "format": "date",
    "pattern": r"^\d{4}-\d{2}-\d{2}$",
    "description": "Date YYYY-MM-DD; defaults to the simulated clock date. Cannot be later than it.",
}
_STATE = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_STATE_LENGTH,
    "description": "US state in English, e.g. 'New York'.",
}
_ORDER_ID = {"type": "integer", "minimum": 1, "maximum": MAX_ORDER_ID}

TOOL_SPECS: list[dict] = [
    {
        "name": "get_order_timeline",
        "description": "Events of one order up to as_of, with shipping mode and promised date.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": _ORDER_ID, "as_of": _AS_OF},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_at_risk_orders",
        "description": "Orders flagged at risk and not completed as of as_of, by promised date.",
        "parameters": {
            "type": "object",
            "properties": {
                "state": _STATE,
                "as_of": _AS_OF,
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "default": DEFAULT_LIMIT,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_shipping_mode_stats",
        "description": "Late rate by shipping mode over orders completed by as_of.",
        "parameters": {
            "type": "object",
            "properties": {"state": _STATE, "as_of": _AS_OF},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "draft_notification",
        "description": "Draft (never sent) customer notification for one at-risk or overdue order.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": _ORDER_ID, "as_of": _AS_OF},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
]

TOOL_FUNCTIONS: dict[str, Callable[..., dict]] = {
    "get_order_timeline": get_order_timeline,
    "list_at_risk_orders": list_at_risk_orders,
    "get_shipping_mode_stats": get_shipping_mode_stats,
    "draft_notification": draft_notification,
}


def _spec(name: str) -> dict:
    return next(s for s in TOOL_SPECS if s["name"] == name)


def call_tool(name: object, arguments: object = None) -> dict:
    """Validate the tool name and argument keys, then run the tool."""
    if not isinstance(name, str) or name not in TOOL_FUNCTIONS:
        return error(INVALID_ARGUMENT, "unknown tool")
    params = _spec(name)["parameters"]
    try:
        args = check_arguments(arguments, params["properties"], params["required"])
    except ToolError as exc:
        return error(exc.code, exc.message)
    return TOOL_FUNCTIONS[name](**args)
