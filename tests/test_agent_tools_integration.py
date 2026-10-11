"""Integration tests for the agent tools against PostgreSQL (as agent_ro)."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

import agent_tools.db as tools_db
from agent_tools.at_risk_orders import list_at_risk_orders
from agent_tools.draft_notification import draft_notification
from agent_tools.order_timeline import get_order_timeline
from agent_tools.registry import call_tool
from agent_tools.results import (
    AS_OF_IN_FUTURE,
    INVALID_ARGUMENT,
    NO_CLOCK,
    ORDER_NOT_FOUND,
    QUERY_TIMEOUT,
    STATE_NOT_FOUND,
    ToolError,
)
from agent_tools.shipping_mode_stats import get_shipping_mode_stats
from etl.db import connect_owner
from tests.agent_output_checks import find_forbidden

pytestmark = pytest.mark.integration

AS_OF = date(2016, 6, 30)
INJECTION = "'; DROP TABLE orders; --"


@pytest.fixture(scope="module", autouse=True)
def require_db(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL is not available")


def owner_scalar(sql: str, params: dict | tuple = ()):
    with connect_owner() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def owner_rows(sql: str, params: dict | tuple = ()) -> list[tuple]:
    with connect_owner() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@pytest.fixture(scope="module")
def clock() -> date:
    return owner_scalar('SELECT "current_date" FROM simulation_clock WHERE id = 1')


@pytest.fixture(scope="module")
def late_flagged_order() -> dict:
    """A non-excluded, flagged order completed at least 2 days after its order date."""
    row = owner_rows(
        """
        SELECT o.order_id, o.order_date, o.sla_due_on, o.completed_on, s.english_name
        FROM orders o
        JOIN risk_flags f ON f.order_id = o.order_id AND f.rule_version = 'v1'
        JOIN state_names s ON s.original_name = o.order_state
        WHERE NOT o.is_excluded
          AND o.completed_on > o.sla_due_on
          AND o.sla_due_on > o.order_date
          AND o.order_date BETWEEN '2016-05-01' AND '2016-06-15'
        ORDER BY o.order_id
        LIMIT 1
        """
    )[0]
    return dict(zip(("order_id", "order_date", "sla_due_on", "completed_on", "state"), row))


@pytest.fixture(scope="module")
def excluded_order_id() -> int:
    return owner_scalar(
        """
        SELECT o.order_id FROM orders o
        JOIN risk_flags f ON f.order_id = o.order_id AND f.rule_version = 'v1'
        WHERE o.is_excluded AND o.order_date <= '2016-06-20'
        ORDER BY o.order_id LIMIT 1
        """
    )


@pytest.fixture(scope="module")
def excluded_ids() -> set[int]:
    return {r[0] for r in owner_rows("SELECT order_id FROM orders WHERE is_excluded")}


def _iso(d: date) -> str:
    return d.isoformat()


def _code(result: dict) -> str:
    assert result["ok"] is False, result
    return result["error"]["code"]


# --- connection ------------------------------------------------------------


def test_every_tool_connects_as_agent_ro(monkeypatch, late_flagged_order) -> None:
    seen: list[tuple[str, str, str]] = []
    original = tools_db.agent_connection

    @contextmanager
    def recording_connection(*args, **kwargs):
        with original(*args, **kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT current_user, current_setting('statement_timeout'), "
                    "current_setting('default_transaction_read_only')"
                )
                seen.append(cur.fetchone())
            yield conn

    monkeypatch.setattr(tools_db, "agent_connection", recording_connection)
    order_id = late_flagged_order["order_id"]
    for result in (
        get_order_timeline(order_id, _iso(AS_OF)),
        list_at_risk_orders(as_of=_iso(AS_OF)),
        get_shipping_mode_stats(as_of=_iso(AS_OF)),
        draft_notification(order_id, _iso(AS_OF)),
    ):
        assert result["ok"], result
    assert seen == [("agent_ro", "5s", "on")] * 4


def test_query_timeout_returns_structured_error() -> None:
    with tools_db.agent_connection(timeout_ms=100) as conn:
        with pytest.raises(ToolError) as exc:
            tools_db.fetch_all(conn, "SELECT pg_sleep(1)")
    assert exc.value.code == QUERY_TIMEOUT


# --- clock -----------------------------------------------------------------


def test_no_clock_errors_for_every_tool(monkeypatch, late_flagged_order) -> None:
    monkeypatch.setattr(tools_db, "read_clock_date", lambda conn: None)
    order_id = late_flagged_order["order_id"]
    for result in (
        get_order_timeline(order_id),
        list_at_risk_orders(),
        get_shipping_mode_stats(),
        draft_notification(order_id),
    ):
        assert _code(result) == NO_CLOCK
        assert result["error"]["message"] == "replay not started"


def test_as_of_defaults_to_clock(clock) -> None:
    assert get_shipping_mode_stats()["as_of"] == _iso(clock)


def test_as_of_in_future_errors_for_every_tool(clock, late_flagged_order) -> None:
    future = _iso(clock + timedelta(days=1))
    order_id = late_flagged_order["order_id"]
    for result in (
        get_order_timeline(order_id, future),
        list_at_risk_orders(as_of=future),
        get_shipping_mode_stats(as_of=future),
        draft_notification(order_id, future),
    ):
        assert _code(result) == AS_OF_IN_FUTURE


# --- as-of correctness -----------------------------------------------------


def test_timeline_as_of(late_flagged_order) -> None:
    o = late_flagged_order
    before = get_order_timeline(o["order_id"], _iso(o["order_date"] - timedelta(days=1)))
    assert _code(before) == ORDER_NOT_FOUND
    assert before["error"]["message"] == "order not found as of that date"

    placed = get_order_timeline(o["order_id"], _iso(o["order_date"]))["data"]
    assert [e["type"] for e in placed["events"]] == ["order_placed"]
    assert placed["completed_on"] is None
    assert placed["status"] == "open"
    assert placed["promised_date"] == _iso(o["sla_due_on"])

    due = get_order_timeline(o["order_id"], _iso(o["sla_due_on"]))["data"]
    assert [e["type"] for e in due["events"]] == ["order_placed", "sla_due"]
    assert due["status"] == "overdue"

    day_before_done = get_order_timeline(
        o["order_id"], _iso(o["completed_on"] - timedelta(days=1))
    )["data"]
    assert day_before_done["completed_on"] is None
    assert "order_completed" not in [e["type"] for e in day_before_done["events"]]

    done = get_order_timeline(o["order_id"], _iso(o["completed_on"]))["data"]
    assert done["completed_on"] == _iso(o["completed_on"])
    assert done["events"][-1]["type"] == "order_completed"
    assert done["status"] == "completed_late"


def _listed_ids(as_of: date, state: str | None = None) -> set[int]:
    result = list_at_risk_orders(state=state, as_of=_iso(as_of), limit=50)
    assert result["ok"], result
    assert not result["data"]["truncated"], "narrow the query to at most 50 orders"
    return {o["order_id"] for o in result["data"]["orders"]}


def test_list_as_of(late_flagged_order) -> None:
    o = late_flagged_order
    order_id, state = o["order_id"], o["state"]
    assert order_id not in _listed_ids(o["order_date"] - timedelta(days=1), state)
    assert order_id in _listed_ids(o["order_date"], state)
    assert order_id in _listed_ids(o["completed_on"] - timedelta(days=1), state)
    assert order_id not in _listed_ids(o["completed_on"], state)


def test_list_overdue_flag_matches_overdue_alerts() -> None:
    result = list_at_risk_orders(as_of=_iso(AS_OF), limit=50)["data"]["orders"]
    overdue_ids = {o["order_id"] for o in result if o["overdue"]}
    alerted = {
        r[0]
        for r in owner_rows(
            "SELECT order_id FROM overdue_alerts WHERE alert_date <= %s", (AS_OF,)
        )
    }
    listed = {o["order_id"] for o in result}
    assert overdue_ids == listed & alerted


def test_stats_as_of_completion() -> None:
    first_completion = owner_scalar(
        "SELECT MIN(completed_on) FROM orders WHERE NOT is_excluded"
    )
    empty = get_shipping_mode_stats(as_of=_iso(first_completion - timedelta(days=1)))
    assert empty["data"]["modes"] == []
    some = get_shipping_mode_stats(as_of=_iso(first_completion))
    assert sum(m["completed_orders"] for m in some["data"]["modes"]) == owner_scalar(
        "SELECT COUNT(*) FROM orders WHERE NOT is_excluded AND completed_on = %s",
        (first_completion,),
    )


def test_draft_as_of(late_flagged_order) -> None:
    o = late_flagged_order
    before = draft_notification(o["order_id"], _iso(o["order_date"] - timedelta(days=1)))
    assert _code(before) == ORDER_NOT_FOUND
    at_risk = draft_notification(o["order_id"], _iso(o["order_date"]))["data"]
    assert at_risk["facts_used"]["variant"] == "at_risk"
    overdue = draft_notification(o["order_id"], _iso(o["sla_due_on"]))["data"]
    assert overdue["facts_used"]["variant"] == "overdue"
    done = draft_notification(o["order_id"], _iso(o["completed_on"]))["data"]
    assert done["draft"] is None and done["sent"] is False


# --- states ----------------------------------------------------------------


def test_new_york_maps_to_spanish_name() -> None:
    for spelling in ("New York", "  new york  ", "NEW YORK"):
        result = list_at_risk_orders(state=spelling, as_of=_iso(AS_OF), limit=50)
        assert result["ok"], result
        assert result["data"]["total_matching"] == owner_scalar(
            """
            SELECT COUNT(*) FROM orders o
            JOIN risk_flags f ON f.order_id = o.order_id AND f.rule_version = 'v1'
            WHERE o.order_state = 'Nueva York' AND NOT o.is_excluded
              AND f.flag_date <= %(d)s AND o.completed_on > %(d)s
            """,
            {"d": AS_OF},
        )
        assert all(r["state"] == "New York" for r in result["data"]["orders"])
    stats = get_shipping_mode_stats(state="new york", as_of=_iso(AS_OF))["data"]["modes"]
    assert sum(m["completed_orders"] for m in stats) == owner_scalar(
        """
        SELECT COUNT(*) FROM orders
        WHERE order_state = 'Nueva York' AND NOT is_excluded AND completed_on <= %s
        """,
        (AS_OF,),
    )


@pytest.mark.parametrize("state", ["Atlantis", "Nueva York", INJECTION])
def test_unknown_state(state) -> None:
    for result in (
        list_at_risk_orders(state=state, as_of=_iso(AS_OF)),
        get_shipping_mode_stats(state=state, as_of=_iso(AS_OF)),
    ):
        assert result == {
            "ok": False,
            "error": {"code": STATE_NOT_FOUND, "message": "state not found"},
        }


# --- limits ----------------------------------------------------------------


@pytest.mark.parametrize("limit", [0, 51, -5, "10", True])
def test_limit_out_of_bounds(limit) -> None:
    assert _code(list_at_risk_orders(as_of=_iso(AS_OF), limit=limit)) == INVALID_ARGUMENT


def test_limit_bounds_accepted() -> None:
    assert list_at_risk_orders(as_of=_iso(AS_OF), limit=1)["data"]["returned"] == 1
    default = list_at_risk_orders(as_of=_iso(AS_OF))["data"]
    assert default["returned"] == min(20, default["total_matching"])
    assert list_at_risk_orders(as_of=_iso(AS_OF), limit=50)["data"]["returned"] <= 50


@pytest.mark.real_data
def test_default_limit_is_twenty() -> None:
    assert list_at_risk_orders(as_of=_iso(AS_OF))["data"]["returned"] == 20


# --- injection -------------------------------------------------------------


def test_injection_strings_only_produce_errors() -> None:
    before = owner_scalar("SELECT COUNT(*) FROM orders")
    results = [
        call_tool("get_order_timeline", {"order_id": INJECTION}),
        call_tool("draft_notification", {"order_id": INJECTION}),
        call_tool("list_at_risk_orders", {"state": INJECTION}),
        call_tool("get_shipping_mode_stats", {"state": INJECTION}),
        call_tool("get_shipping_mode_stats", {"as_of": INJECTION}),
    ]
    assert [r["ok"] for r in results] == [False] * len(results)
    assert owner_scalar("SELECT to_regclass('public.orders') IS NOT NULL") is True
    assert owner_scalar("SELECT COUNT(*) FROM orders") == before


# --- excluded orders -------------------------------------------------------


def test_excluded_never_in_lists(excluded_ids) -> None:
    """Total open at-risk counts equal SQL counts that skip excluded orders."""
    for day in range(0, 150, 7):
        as_of = date(2016, 4, 1) + timedelta(days=day)
        result = list_at_risk_orders(as_of=_iso(as_of), limit=50)["data"]
        assert not {o["order_id"] for o in result["orders"]} & excluded_ids
        assert result["total_matching"] == owner_scalar(
            """
            SELECT COUNT(*) FROM risk_flags f JOIN orders o ON o.order_id = f.order_id
            WHERE f.rule_version = 'v1' AND f.flag_date <= %(d)s
              AND NOT o.is_excluded AND o.completed_on > %(d)s
            """,
            {"d": as_of},
        )


@pytest.mark.real_data
def test_stats_exclude_excluded_orders(clock) -> None:
    modes = get_shipping_mode_stats(as_of=_iso(clock))["data"]["modes"]
    assert sum(m["completed_orders"] for m in modes) == 7887


def test_excluded_timeline_and_draft(excluded_order_id, clock) -> None:
    timeline = get_order_timeline(excluded_order_id, _iso(clock))["data"]
    assert [e["type"] for e in timeline["events"]] == ["order_placed"]
    assert timeline["completed_on"] is None
    assert timeline["status"] == "no_updates"
    assert timeline["message"] == "No further updates are available for this order."
    draft = draft_notification(excluded_order_id, _iso(clock))["data"]
    assert draft["draft"] is None and draft["sent"] is False
    assert draft["message"] == "A notification draft is not available for this order."


# --- counts match independent SQL ------------------------------------------


def test_open_at_risk_count_matches_sql() -> None:
    result = list_at_risk_orders(as_of=_iso(AS_OF), limit=50)["data"]
    independent = owner_scalar(
        """
        SELECT COUNT(*) FROM risk_flags f
        JOIN orders o ON o.order_id = f.order_id
        WHERE f.rule_version = 'v1' AND f.flag_date <= %(d)s
          AND NOT o.is_excluded AND o.completed_on > %(d)s
        """,
        {"d": AS_OF},
    )
    assert result["total_matching"] == independent == result["returned"]


def test_stats_match_sql() -> None:
    modes = get_shipping_mode_stats(as_of=_iso(AS_OF))["data"]["modes"]
    expected = owner_rows(
        """
        SELECT shipping_mode, COUNT(*),
               COUNT(*) FILTER (WHERE late_label)
        FROM orders WHERE NOT is_excluded AND completed_on <= %s
        GROUP BY shipping_mode ORDER BY shipping_mode
        """,
        (AS_OF,),
    )
    assert [(m["shipping_mode"], m["completed_orders"], m["late_orders"]) for m in modes] == [
        tuple(r) for r in expected
    ]


# --- drafts ----------------------------------------------------------------


def test_drafts_have_no_new_dates_or_internal_reasons() -> None:
    orders = list_at_risk_orders(as_of=_iso(AS_OF), limit=50)["data"]["orders"]
    variants = set()
    for o in orders:
        data = draft_notification(o["order_id"], _iso(AS_OF))["data"]
        text = data["draft"]
        variants.add(data["facts_used"]["variant"])
        assert data["sent"] is False
        assert re.findall(r"\d{4}-\d{2}-\d{2}", text) == [o["promised_date"]]
        assert not re.search(r"guarantee", text, re.IGNORECASE)
        assert not re.search(
            r"\b(rule|v1|flag\w*|training|rate|risk|model|%)\b|%", text, re.IGNORECASE
        )
    assert variants <= {"overdue", "at_risk"}


@pytest.mark.real_data
def test_drafts_cover_both_variants() -> None:
    orders = list_at_risk_orders(as_of=_iso(AS_OF), limit=50)["data"]["orders"]
    variants = {
        draft_notification(o["order_id"], _iso(AS_OF))["data"]["facts_used"]["variant"]
        for o in orders
    }
    assert variants == {"overdue", "at_risk"}


# --- forbidden fields --------------------------------------------------------


def test_no_forbidden_fields_in_any_output(late_flagged_order, excluded_order_id, clock) -> None:
    o = late_flagged_order
    dates = [o["order_date"], o["sla_due_on"], o["completed_on"], AS_OF, clock]
    outputs = []
    for d in dates:
        for order_id in (o["order_id"], excluded_order_id):
            outputs.append(get_order_timeline(order_id, _iso(d)))
            outputs.append(draft_notification(order_id, _iso(d)))
        outputs.append(list_at_risk_orders(as_of=_iso(d), limit=50))
        outputs.append(get_shipping_mode_stats(as_of=_iso(d)))
        outputs.append(get_shipping_mode_stats(state="Texas", as_of=_iso(d)))
    outputs.append(call_tool("get_order_timeline", {"order_id": 99999999}))
    outputs.append(call_tool("list_at_risk_orders", {"state": "Atlantis"}))
    assert find_forbidden(outputs) == []
