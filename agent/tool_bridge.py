"""Turn one model tool call into a tool result: check, fill as_of, run, time."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date

from agent.provider import ToolCall, ToolResult
from agent_tools.registry import TOOL_FUNCTIONS, call_tool
from agent_tools.results import INVALID_ARGUMENT, error

ToolRunner = Callable[[str, dict], dict]

TOOL_FAILED = "TOOL_FAILED"
TOOL_CALL_LIMIT = "TOOL_CALL_LIMIT"


def call_record(
    name: object, arguments: object, duration_ms: float, result: dict, executed: bool
) -> dict:
    return {
        "name": name,
        "arguments": arguments,
        "duration_ms": round(duration_ms, 1),
        "ok": bool(result.get("ok")),
        "error_code": None if result.get("ok") else result.get("error", {}).get("code"),
        "executed": executed,
    }


def _rejected(call: ToolCall, content: dict) -> tuple[ToolResult, dict]:
    return (
        ToolResult(call_id=call.id, content=content, is_error=True),
        call_record(call.name, call.arguments, 0.0, content, executed=False),
    )


def limit_reached(call: ToolCall) -> tuple[ToolResult, dict]:
    return _rejected(
        call,
        error(TOOL_CALL_LIMIT, "tool-call limit reached; answer from the results you have"),
    )


def run_tool_call(
    call: ToolCall, as_of: date, runner: ToolRunner = call_tool
) -> tuple[ToolResult, dict]:
    """Unknown tools and non-object arguments are rejected here and never executed."""
    if call.name not in TOOL_FUNCTIONS:
        return _rejected(call, error(INVALID_ARGUMENT, "unknown tool"))
    if not isinstance(call.arguments, dict):
        return _rejected(call, error(INVALID_ARGUMENT, "arguments must be an object"))

    arguments = dict(call.arguments)
    arguments.setdefault("as_of", as_of.isoformat())
    start = time.perf_counter()
    try:
        result = runner(call.name, arguments)
    except Exception:
        result = error(TOOL_FAILED, "the tool failed unexpectedly")
    duration_ms = (time.perf_counter() - start) * 1000
    return (
        ToolResult(call_id=call.id, content=result, is_error=not result.get("ok", False)),
        call_record(call.name, arguments, duration_ms, result, executed=True),
    )
