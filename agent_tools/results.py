"""Structured tool results and error codes."""

from __future__ import annotations

from datetime import date

NO_CLOCK = "NO_CLOCK"
AS_OF_IN_FUTURE = "AS_OF_IN_FUTURE"
ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
STATE_NOT_FOUND = "STATE_NOT_FOUND"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
QUERY_TIMEOUT = "QUERY_TIMEOUT"


class ToolError(Exception):
    """A failure that is returned to the caller as a structured error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def ok(as_of: date, data: dict) -> dict:
    return {"ok": True, "as_of": as_of.isoformat(), "data": data}


def error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}
