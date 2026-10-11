"""Pure helpers for day-ordered event replay and overdue alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


class ReplayNotStartedError(RuntimeError):
    """Raised when simulation_clock has no row.

    Future as-of readers must treat a missing clock as this error
    ("replay not started") and must never fall back to the real date.
    """


@dataclass(frozen=True)
class OrderReplayRow:
    """Minimal order fields needed to plan one simulated day."""

    order_id: int
    order_date: date
    sla_due_on: date
    completed_on: date | None
    is_excluded: bool


@dataclass(frozen=True)
class DayPlan:
    """Work to perform on one simulated day, in processing order."""

    order_placed: tuple[int, ...]
    order_completed: tuple[int, ...]
    sla_due: tuple[int, ...]
    overdue_alerts: tuple[int, ...]


def require_clock_date(clock_date: date | None) -> date:
    """Return the clock date, or raise if replay has not started."""
    if clock_date is None:
        raise ReplayNotStartedError(
            "replay not started: simulation_clock has no row; "
            "do not fall back to the real date"
        )
    return clock_date


def should_raise_overdue(
    *,
    is_excluded: bool,
    sla_due_on: date,
    day: date,
    has_order_completed_event: bool,
) -> bool:
    """
    Overdue alert on sla_due day if the order is not yet completed.

    Same-day ordering writes order_completed before this check, so an order
    completed on its due date (including Same Day) is on time.
    """
    if is_excluded:
        return False
    if day != sla_due_on:
        return False
    return not has_order_completed_event


def plan_day(orders: list[OrderReplayRow], day: date) -> DayPlan:
    """
    Decide events and overdue alerts for one day.

    Processing order: order_placed, then order_completed, then sla_due check.
    Excluded orders emit only order_placed.
    """
    placed: list[int] = []
    completed: list[int] = []
    sla_due: list[int] = []
    overdue: list[int] = []

    for order in orders:
        if order.order_date == day:
            placed.append(order.order_id)

    for order in orders:
        if order.is_excluded:
            continue
        if order.completed_on == day:
            completed.append(order.order_id)

    completed_ids = set(completed)
    for order in orders:
        if order.is_excluded:
            continue
        if order.sla_due_on != day:
            continue
        sla_due.append(order.order_id)
        # After same-day completions: completed today counts as already done.
        has_completed = order.order_id in completed_ids or (
            order.completed_on is not None and order.completed_on < day
        )
        if should_raise_overdue(
            is_excluded=order.is_excluded,
            sla_due_on=order.sla_due_on,
            day=day,
            has_order_completed_event=has_completed,
        ):
            overdue.append(order.order_id)

    return DayPlan(
        order_placed=tuple(placed),
        order_completed=tuple(completed),
        sla_due=tuple(sla_due),
        overdue_alerts=tuple(overdue),
    )


def date_range_inclusive(start: date, end: date) -> list[date]:
    """Return each calendar day from start through end inclusive."""
    if end < start:
        return []
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def next_replay_start(
    clock_date: date | None, earliest_data_date: date, to_date: date
) -> date | None:
    """
    First day to process for this run, or None if there is nothing to do.

    No clock row means start at earliest_data_date (replay not yet started).
    """
    if clock_date is None:
        start = earliest_data_date
    else:
        start = clock_date + timedelta(days=1)
    if start > to_date:
        return None
    return start
