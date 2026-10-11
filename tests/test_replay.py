"""Unit tests for event replay ordering and the overdue rule."""

from __future__ import annotations

from datetime import date

import pytest

from etl.replay import (
    DayPlan,
    OrderReplayRow,
    ReplayNotStartedError,
    date_range_inclusive,
    next_replay_start,
    plan_day,
    require_clock_date,
    should_raise_overdue,
)


def test_require_clock_date_errors_when_missing() -> None:
    with pytest.raises(ReplayNotStartedError, match="replay not started"):
        require_clock_date(None)
    assert require_clock_date(date(2016, 4, 1)) == date(2016, 4, 1)


def test_should_raise_overdue_on_due_date_if_not_completed() -> None:
    assert (
        should_raise_overdue(
            is_excluded=False,
            sla_due_on=date(2016, 4, 5),
            day=date(2016, 4, 5),
            has_order_completed_event=False,
        )
        is True
    )


def test_completed_exactly_on_due_date_is_on_time() -> None:
    assert (
        should_raise_overdue(
            is_excluded=False,
            sla_due_on=date(2016, 4, 5),
            day=date(2016, 4, 5),
            has_order_completed_event=True,
        )
        is False
    )


def test_excluded_never_overdue() -> None:
    assert (
        should_raise_overdue(
            is_excluded=True,
            sla_due_on=date(2016, 4, 5),
            day=date(2016, 4, 5),
            has_order_completed_event=False,
        )
        is False
    )


def test_plan_day_ordering_and_rules() -> None:
    day = date(2016, 4, 1)
    on_time = OrderReplayRow(
        order_id=1,
        order_date=day,
        sla_due_on=day,
        completed_on=day,
        is_excluded=False,
    )
    same_day = OrderReplayRow(
        order_id=2,
        order_date=day,
        sla_due_on=day,  # scheduled_days = 0
        completed_on=day,
        is_excluded=False,
    )
    late = OrderReplayRow(
        order_id=3,
        order_date=day,
        sla_due_on=day,
        completed_on=date(2016, 4, 3),
        is_excluded=False,
    )
    excluded = OrderReplayRow(
        order_id=4,
        order_date=day,
        sla_due_on=day,
        completed_on=None,
        is_excluded=True,
    )

    plan = plan_day([on_time, same_day, late, excluded], day)
    assert plan == DayPlan(
        order_placed=(1, 2, 3, 4),
        order_completed=(1, 2),
        sla_due=(1, 2, 3),
        overdue_alerts=(3,),
    )
    # Excluded: placed only — not in completed/sla_due/overdue.
    assert 4 not in plan.order_completed
    assert 4 not in plan.sla_due
    assert 4 not in plan.overdue_alerts


def test_plan_day_late_order_alerts_on_sla_day_only() -> None:
    order = OrderReplayRow(
        order_id=10,
        order_date=date(2016, 4, 1),
        sla_due_on=date(2016, 4, 2),
        completed_on=date(2016, 4, 4),
        is_excluded=False,
    )
    assert plan_day([order], date(2016, 4, 1)).overdue_alerts == ()
    assert plan_day([order], date(2016, 4, 2)).overdue_alerts == (10,)
    assert plan_day([order], date(2016, 4, 4)).overdue_alerts == ()


def test_date_range_and_next_start() -> None:
    assert date_range_inclusive(date(2016, 4, 1), date(2016, 4, 3)) == [
        date(2016, 4, 1),
        date(2016, 4, 2),
        date(2016, 4, 3),
    ]
    assert date_range_inclusive(date(2016, 4, 3), date(2016, 4, 1)) == []
    assert next_replay_start(None, date(2016, 4, 1), date(2016, 8, 31)) == date(
        2016, 4, 1
    )
    assert next_replay_start(
        date(2016, 4, 10), date(2016, 4, 1), date(2016, 8, 31)
    ) == date(2016, 4, 11)
    assert next_replay_start(date(2016, 8, 31), date(2016, 4, 1), date(2016, 8, 31)) is None
