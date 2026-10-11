"""Argument validation mirroring the JSON Schemas in registry.py."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from agent_tools.results import INVALID_ARGUMENT, ToolError

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_STATE_LENGTH = 60
MAX_ORDER_ID = 2**31 - 1
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_order_id(value: object) -> int:
    if not _is_int(value) or not 1 <= value <= MAX_ORDER_ID:
        raise ToolError(INVALID_ARGUMENT, "order_id must be a positive integer")
    return value


def parse_as_of(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, str) and _ISO_DATE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ToolError(INVALID_ARGUMENT, "as_of must be a date formatted YYYY-MM-DD")


def parse_state(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if 1 <= len(stripped) <= MAX_STATE_LENGTH:
            return stripped
    raise ToolError(
        INVALID_ARGUMENT, f"state must be a non-empty string of at most {MAX_STATE_LENGTH} characters"
    )


def parse_limit(value: object) -> int:
    if value is None:
        return DEFAULT_LIMIT
    if not _is_int(value) or not 1 <= value <= MAX_LIMIT:
        raise ToolError(INVALID_ARGUMENT, f"limit must be an integer from 1 to {MAX_LIMIT}")
    return value


def check_arguments(
    arguments: object, allowed: Iterable[str], required: Iterable[str]
) -> dict:
    """Reject non-objects, unknown arguments, and missing required arguments."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolError(INVALID_ARGUMENT, "arguments must be an object")
    unknown = sorted(set(arguments) - set(allowed))
    if unknown:
        raise ToolError(INVALID_ARGUMENT, f"unknown arguments: {', '.join(map(str, unknown))}")
    missing = sorted(set(required) - set(arguments))
    if missing:
        raise ToolError(INVALID_ARGUMENT, f"missing required arguments: {', '.join(missing)}")
    return arguments
