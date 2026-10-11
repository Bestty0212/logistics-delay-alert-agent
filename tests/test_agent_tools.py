"""Unit tests for agent tools: validation, results, status, templates, registry."""

from __future__ import annotations

import re
from datetime import date

import pytest

from agent_tools.draft_notification import (
    AT_RISK_TEMPLATE,
    OVERDUE_TEMPLATE,
    choose_variant,
    render_draft,
)
from agent_tools.orders import order_status
from agent_tools.registry import TOOL_FUNCTIONS, TOOL_SPECS, call_tool
from agent_tools.results import INVALID_ARGUMENT, ToolError, error, ok
from agent_tools.shipping_mode_stats import mode_row
from agent_tools.validation import (
    DEFAULT_LIMIT,
    check_arguments,
    parse_as_of,
    parse_limit,
    parse_order_id,
    parse_state,
)
from tests.agent_output_checks import find_forbidden

INJECTION = "'; DROP TABLE orders; --"


def _code(exc_info) -> str:
    return exc_info.value.code


# --- results ---------------------------------------------------------------


def test_ok_and_error_shapes() -> None:
    assert ok(date(2016, 6, 30), {"x": 1}) == {
        "ok": True, "as_of": "2016-06-30", "data": {"x": 1},
    }
    assert error("NO_CLOCK", "replay not started") == {
        "ok": False, "error": {"code": "NO_CLOCK", "message": "replay not started"},
    }


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize("value", [1, 37065, 2**31 - 1])
def test_parse_order_id_accepts_positive_ints(value) -> None:
    assert parse_order_id(value) == value


@pytest.mark.parametrize("value", [0, -1, 2**31, True, 1.0, "37065", INJECTION, None])
def test_parse_order_id_rejects(value) -> None:
    with pytest.raises(ToolError) as exc:
        parse_order_id(value)
    assert _code(exc) == INVALID_ARGUMENT


def test_parse_as_of() -> None:
    assert parse_as_of(None) is None
    assert parse_as_of("2016-06-30") == date(2016, 6, 30)


@pytest.mark.parametrize("value", ["2016-6-30", "2016-02-30", "yesterday", 20160630, INJECTION])
def test_parse_as_of_rejects(value) -> None:
    with pytest.raises(ToolError) as exc:
        parse_as_of(value)
    assert _code(exc) == INVALID_ARGUMENT


def test_parse_state() -> None:
    assert parse_state(None) is None
    assert parse_state("  New York ") == "New York"
    assert parse_state(INJECTION) == INJECTION  # passed as a bound parameter, never SQL
    for bad in ("", "   ", "x" * 61, 5):
        with pytest.raises(ToolError):
            parse_state(bad)


@pytest.mark.parametrize("value", [1, 20, 50])
def test_parse_limit_bounds_ok(value) -> None:
    assert parse_limit(value) == value


def test_parse_limit_default() -> None:
    assert parse_limit(None) == DEFAULT_LIMIT == 20


@pytest.mark.parametrize("value", [0, 51, -1, 500, "5", True, 1.5])
def test_parse_limit_rejects(value) -> None:
    with pytest.raises(ToolError) as exc:
        parse_limit(value)
    assert _code(exc) == INVALID_ARGUMENT


def test_check_arguments() -> None:
    assert check_arguments(None, ["a"], []) == {}
    assert check_arguments({"a": 1}, ["a"], ["a"]) == {"a": 1}
    for args, required in (([1], []), ({"sql": "x"}, []), ({}, ["a"])):
        with pytest.raises(ToolError):
            check_arguments(args, ["a"], required)


# --- status ----------------------------------------------------------------


def _order(**overrides) -> dict:
    base = {
        "is_excluded": False,
        "completed_on": None,
        "sla_due_on": date(2016, 6, 28),
    }
    base.update(overrides)
    return base


def test_order_status_values() -> None:
    as_of = date(2016, 6, 30)
    assert order_status(_order(), date(2016, 6, 27)) == "open"
    assert order_status(_order(), date(2016, 6, 28)) == "overdue"  # due day, not completed
    assert order_status(_order(completed_on=date(2016, 6, 28)), as_of) == "completed_on_time"
    assert order_status(_order(completed_on=date(2016, 6, 29)), as_of) == "completed_late"
    assert order_status(_order(is_excluded=True), as_of) == "no_updates"


# --- drafts ----------------------------------------------------------------


def test_choose_variant() -> None:
    assert choose_variant("overdue", True) == "overdue"
    assert choose_variant("overdue", False) == "overdue"
    assert choose_variant("open", True) == "at_risk"
    assert choose_variant("open", False) is None
    assert choose_variant("completed_late", True) is None
    assert choose_variant("no_updates", True) is None


@pytest.mark.parametrize("variant", ["overdue", "at_risk"])
def test_render_draft_uses_only_allowed_facts(variant) -> None:
    text = render_draft(variant, 37065, date(2016, 6, 27), "Second Class")
    assert "37065" in text and "Second Class" in text
    assert re.findall(r"\d{4}-\d{2}-\d{2}", text) == ["2016-06-27"]
    assert not re.search(r"guarantee", text, re.IGNORECASE)
    assert not re.search(r"\b(rule|v1|flag\w*|training|rate|risk|model)\b", text, re.IGNORECASE)
    assert find_forbidden(text) == []


def test_templates_have_no_date_literals() -> None:
    for template in (AT_RISK_TEMPLATE, OVERDUE_TEMPLATE):
        assert not re.search(r"\d", template)


# --- stats -----------------------------------------------------------------


def test_mode_row_small_sample() -> None:
    assert mode_row("Same Day", 29, 10)["small_sample"] is True
    assert mode_row("Same Day", 30, 10)["small_sample"] is False
    assert mode_row("First Class", 4, 3)["late_rate"] == 0.75


# --- registry --------------------------------------------------------------


def test_specs_match_functions() -> None:
    assert {s["name"] for s in TOOL_SPECS} == set(TOOL_FUNCTIONS)
    for spec in TOOL_SPECS:
        params = spec["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False


def test_call_tool_rejects_unknown_tool_and_arguments() -> None:
    assert call_tool("drop_orders", {})["error"]["code"] == INVALID_ARGUMENT
    assert call_tool(None)["error"]["code"] == INVALID_ARGUMENT
    result = call_tool("list_at_risk_orders", {"sql": "SELECT 1"})
    assert result["error"]["code"] == INVALID_ARGUMENT
    assert call_tool("get_order_timeline", {})["error"]["code"] == INVALID_ARGUMENT
    assert call_tool("get_order_timeline", "not an object")["error"]["code"] == INVALID_ARGUMENT


def test_validation_runs_before_any_connection(monkeypatch) -> None:
    import agent_tools.db as db

    def fail(*args, **kwargs):
        raise AssertionError("should not connect for invalid arguments")

    monkeypatch.setattr(db, "agent_connection", fail)
    assert call_tool("get_order_timeline", {"order_id": INJECTION})["error"]["code"] == INVALID_ARGUMENT
    assert call_tool("list_at_risk_orders", {"limit": 0})["error"]["code"] == INVALID_ARGUMENT


# --- forbidden-output checker itself ----------------------------------------


def test_find_forbidden_is_recursive() -> None:
    assert find_forbidden({"a": [{"b": {"late_label": True}}]}) == [
        "forbidden key at $.a[0].b.late_label"
    ]
    assert find_forbidden({"msg": "Order was CANCELED"})
    assert find_forbidden(["ok", {"x": "Late delivery"}])
    assert find_forbidden({"late_orders": 3, "status": "completed_late"}) == []
