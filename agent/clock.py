"""Simulated clock for the agent session (read as agent_ro; never the real date)."""

from __future__ import annotations

from datetime import date

from agent_tools.db import agent_connection, read_clock_date


class SessionDateError(Exception):
    """The session date cannot be set (no clock, or a date after the clock)."""


def read_clock() -> date | None:
    with agent_connection() as conn:
        return read_clock_date(conn)


def resolve_session_as_of(requested: date | None, clock: date | None) -> date:
    if clock is None:
        raise SessionDateError("replay not started")
    if requested is None:
        return clock
    if requested > clock:
        raise SessionDateError(
            f"--as-of {requested.isoformat()} is later than the simulated clock "
            f"({clock.isoformat()})"
        )
    return requested
