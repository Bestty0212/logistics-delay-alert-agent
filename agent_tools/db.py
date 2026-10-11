"""agent_ro connections, timeouts, and the as-of and state helpers shared by all tools."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date

import psycopg
from psycopg.rows import dict_row

from agent_tools.results import (
    AS_OF_IN_FUTURE,
    NO_CLOCK,
    QUERY_TIMEOUT,
    STATE_NOT_FOUND,
    ToolError,
    error,
    ok,
)
from agent_tools.validation import parse_as_of
from etl.db import agent_ro_connect_kwargs

STATEMENT_TIMEOUT_MS = 5000


@contextmanager
def agent_connection(timeout_ms: int = STATEMENT_TIMEOUT_MS) -> Iterator[psycopg.Connection]:
    """Connect as agent_ro with a statement timeout and read-only transactions."""
    options = f"-c statement_timeout={int(timeout_ms)} -c default_transaction_read_only=on"
    with psycopg.connect(**agent_ro_connect_kwargs(), options=options) as conn:
        yield conn


def fetch_all(conn: psycopg.Connection, sql: str, params: dict | tuple = ()) -> list[dict]:
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []
    except psycopg.errors.QueryCanceled as exc:
        conn.rollback()
        raise ToolError(QUERY_TIMEOUT, "the query took too long and was stopped") from exc


def fetch_one(conn: psycopg.Connection, sql: str, params: dict | tuple = ()) -> dict | None:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


def read_clock_date(conn: psycopg.Connection) -> date | None:
    """Simulated clock date, or None when replay has not started (no row)."""
    row = fetch_one(conn, 'SELECT "current_date" AS clock FROM simulation_clock WHERE id = 1')
    return row["clock"] if row else None


def resolve_as_of(conn: psycopg.Connection, as_of: date | None) -> date:
    """Default to the simulated clock; never the real date; the future is not visible."""
    clock = read_clock_date(conn)
    if clock is None:
        raise ToolError(NO_CLOCK, "replay not started")
    if as_of is None:
        return clock
    if as_of > clock:
        raise ToolError(AS_OF_IN_FUTURE, "as_of is later than the simulated clock date")
    return as_of


def resolve_state(conn: psycopg.Connection, state: str | None) -> str | None:
    """Map an English state name (case-insensitive, trimmed) to the stored value."""
    if state is None:
        return None
    row = fetch_one(
        conn,
        "SELECT original_name FROM state_names WHERE LOWER(english_name) = LOWER(%s)",
        (state.strip(),),
    )
    if row is None:
        raise ToolError(STATE_NOT_FOUND, "state not found")
    return row["original_name"]


def run_tool(
    as_of_raw: object,
    validate: Callable[[], dict],
    body: Callable[[psycopg.Connection, date, dict], dict],
) -> dict:
    """Validate arguments, open an agent_ro connection, resolve the clock, run body."""
    try:
        args = validate()
        as_of = parse_as_of(as_of_raw)
        with agent_connection() as conn:
            resolved = resolve_as_of(conn, as_of)
            data = body(conn, resolved, args)
        return ok(resolved, data)
    except ToolError as exc:
        return error(exc.code, exc.message)
