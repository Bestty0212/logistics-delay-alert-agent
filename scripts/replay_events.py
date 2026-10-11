#!/usr/bin/env python3
"""Replay orders onto a simulated clock and raise deterministic overdue alerts."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.db import connect_owner  # noqa: E402
from etl.env import apply_env_file  # noqa: E402
from etl.replay import date_range_inclusive, next_replay_start  # noqa: E402

ENV_PATH = ROOT / ".env"

# Readers of simulation_clock: a missing row means "replay not started".
# Never fall back to the real (wall-clock) date.


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--to",
        type=date.fromisoformat,
        help="Advance the simulated clock day by day up to this date (inclusive)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear events, overdue_alerts, and the simulation clock",
    )
    parser.add_argument(
        "--seconds-per-day",
        type=float,
        default=0.0,
        help="Sleep this many seconds after each simulated day (demo pacing)",
    )
    return parser.parse_args(argv)


def reset_replay(conn: psycopg.Connection) -> None:
    """Clear replay outputs. Leaves no simulation_clock row."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE overdue_alerts, events RESTART IDENTITY")
        cur.execute("DELETE FROM simulation_clock")
    conn.commit()


def fetch_clock_date(conn: psycopg.Connection) -> date | None:
    """Return current_date, or None if replay has not started (no row)."""
    with conn.cursor() as cur:
        cur.execute('SELECT "current_date" FROM simulation_clock WHERE id = 1')
        row = cur.fetchone()
    return row[0] if row else None


def fetch_earliest_data_date(conn: psycopg.Connection) -> date:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT LEAST(
                (SELECT MIN(order_date) FROM orders),
                (SELECT MIN(sla_due_on) FROM orders WHERE NOT is_excluded),
                (SELECT MIN(completed_on) FROM orders WHERE NOT is_excluded)
            )
            """
        )
        earliest = cur.fetchone()[0]
    if earliest is None:
        raise RuntimeError("orders table is empty; cannot replay")
    return earliest


def set_clock_date(conn: psycopg.Connection, day: date) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO simulation_clock (id, "current_date")
            VALUES (1, %s)
            ON CONFLICT (id) DO UPDATE
            SET "current_date" = EXCLUDED."current_date"
            """,
            (day,),
        )


def process_day(conn: psycopg.Connection, day: date) -> None:
    """
    Process one simulated day in design order:
    order_placed, then order_completed, then sla_due (+ overdue check).
    Idempotent via ON CONFLICT DO NOTHING.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (order_id, event_type, event_date)
            SELECT order_id, 'order_placed', order_date
            FROM orders
            WHERE order_date = %s
            ON CONFLICT (order_id, event_type) DO NOTHING
            """,
            (day,),
        )
        cur.execute(
            """
            INSERT INTO events (order_id, event_type, event_date)
            SELECT order_id, 'order_completed', completed_on
            FROM orders
            WHERE NOT is_excluded AND completed_on = %s
            ON CONFLICT (order_id, event_type) DO NOTHING
            """,
            (day,),
        )
        cur.execute(
            """
            INSERT INTO events (order_id, event_type, event_date)
            SELECT order_id, 'sla_due', sla_due_on
            FROM orders
            WHERE NOT is_excluded AND sla_due_on = %s
            ON CONFLICT (order_id, event_type) DO NOTHING
            """,
            (day,),
        )
        # Overdue if sla_due today and no order_completed event yet
        # (completions for today were written above).
        cur.execute(
            """
            INSERT INTO overdue_alerts (order_id, alert_date)
            SELECT o.order_id, o.sla_due_on
            FROM orders o
            WHERE NOT o.is_excluded
              AND o.sla_due_on = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM events e
                  WHERE e.order_id = o.order_id
                    AND e.event_type = 'order_completed'
              )
            ON CONFLICT (order_id) DO NOTHING
            """,
            (day,),
        )
    set_clock_date(conn, day)
    conn.commit()


def advance_to(
    conn: psycopg.Connection, to_date: date, seconds_per_day: float
) -> tuple[date | None, date | None]:
    """
    Advance the clock day by day up to to_date.
    Returns (first_day_processed, last_day_processed) for this run.
    """
    clock = fetch_clock_date(conn)
    earliest = fetch_earliest_data_date(conn)
    start = next_replay_start(clock, earliest, to_date)
    if start is None:
        print(f"Nothing to do: clock already at or beyond {to_date.isoformat()}")
        return None, None

    first: date | None = None
    last: date | None = None
    for day in date_range_inclusive(start, to_date):
        process_day(conn, day)
        if first is None:
            first = day
        last = day
        if seconds_per_day > 0:
            time.sleep(seconds_per_day)
    return first, last


def fetch_report_counts(conn: psycopg.Connection) -> dict[str, int | date | float | None]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_type, COUNT(*)
            FROM events
            GROUP BY event_type
            """
        )
        by_type = {row[0]: row[1] for row in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM overdue_alerts")
        overdue_count = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*) FROM orders
            WHERE NOT is_excluded AND late_label = TRUE
            """
        )
        late_label_true = cur.fetchone()[0]
        cur.execute("SELECT MIN(event_date), MAX(event_date) FROM events")
        min_event, max_event = cur.fetchone()
        cur.execute(
            """
            SELECT COUNT(*)
            FROM overdue_alerts a
            JOIN orders o ON o.order_id = a.order_id
            WHERE o.completed_on IS NOT NULL
              AND a.alert_date < o.completed_on
            """
        )
        alerts_before_completed = cur.fetchone()[0]
        cur.execute(
            """
            SELECT
                AVG((o.completed_on - a.alert_date)),
                MAX((o.completed_on - a.alert_date))
            FROM overdue_alerts a
            JOIN orders o ON o.order_id = a.order_id
            WHERE o.completed_on IS NOT NULL
            """
        )
        avg_days, max_days = cur.fetchone()
    return {
        "order_placed": by_type.get("order_placed", 0),
        "sla_due": by_type.get("sla_due", 0),
        "order_completed": by_type.get("order_completed", 0),
        "overdue_alerts": overdue_count,
        "late_label_true": late_label_true,
        "min_event_date": min_event,
        "max_event_date": max_event,
        "alerts_before_completed": alerts_before_completed,
        "avg_days_alert_to_completed": float(avg_days) if avg_days is not None else None,
        "max_days_alert_to_completed": int(max_days) if max_days is not None else None,
    }


def print_report(
    *,
    run_first: date | None,
    run_last: date | None,
    counts: dict[str, int | date | float | None],
) -> None:
    print(f"order_placed events: {counts['order_placed']}")
    print(f"sla_due events: {counts['sla_due']}")
    print(f"order_completed events: {counts['order_completed']}")
    print(f"overdue alerts: {counts['overdue_alerts']}")
    print(f"non-excluded orders with late_label = true: {counts['late_label_true']}")
    if run_first is None or run_last is None:
        print("simulated dates processed this run: none")
    else:
        print(
            "simulated dates processed this run: "
            f"{run_first.isoformat()} .. {run_last.isoformat()}"
        )
    min_e = counts["min_event_date"]
    max_e = counts["max_event_date"]
    if min_e is None or max_e is None:
        print("event_date min/max in events table: none")
    else:
        print(
            "event_date min/max in events table: "
            f"{min_e.isoformat()} .. {max_e.isoformat()}"
        )
    print(
        "overdue alerts fired before completed_on: "
        f"{counts['alerts_before_completed']}"
    )
    avg_days = counts["avg_days_alert_to_completed"]
    max_days = counts["max_days_alert_to_completed"]
    if avg_days is None or max_days is None:
        print("days alert→completed_on avg/max: n/a")
    else:
        print(
            "days alert→completed_on avg/max: "
            f"{avg_days:.2f} / {max_days}"
        )


def main(argv: list[str] | None = None) -> int:
    apply_env_file(ENV_PATH, os.environ)
    args = parse_args(argv)

    if not args.reset and args.to is None:
        print("Provide --reset and/or --to YYYY-MM-DD", file=sys.stderr)
        return 2

    with connect_owner() as conn:
        if args.reset:
            reset_replay(conn)
            print("reset complete: events, overdue_alerts cleared; no clock row")

        run_first = None
        run_last = None
        if args.to is not None:
            run_first, run_last = advance_to(conn, args.to, args.seconds_per_day)

        counts = fetch_report_counts(conn)
        print_report(run_first=run_first, run_last=run_last, counts=counts)

        # Equality is required after a --to run (full replay must match).
        if args.to is not None and counts["overdue_alerts"] != counts["late_label_true"]:
            print(
                "ERROR: overdue alerts count must equal late_label = true count "
                f"({counts['overdue_alerts']} != {counts['late_label_true']})",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
