#!/usr/bin/env python3
"""Write reports/data_summary.md: counts read from the loaded database (owner role, read-only)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from etl.db import connect_owner  # noqa: E402
from etl.env import apply_env_file  # noqa: E402

REPORT_PATH = ROOT / "reports" / "data_summary.md"

QUERIES = {
    "order_items": "SELECT COUNT(*) FROM order_items",
    "excluded_items": """
        SELECT COUNT(*) FROM order_items i JOIN orders o USING (order_id) WHERE o.is_excluded
    """,
    "orders": "SELECT COUNT(*) FROM orders",
    "excluded_orders": "SELECT COUNT(*) FROM orders WHERE is_excluded",
    "evaluated_orders": "SELECT COUNT(*) FROM orders WHERE NOT is_excluded",
    "first_order_date": "SELECT MIN(order_date) FROM orders",
    "last_order_date": "SELECT MAX(order_date) FROM orders",
    "states": "SELECT COUNT(*) FROM state_names",
    "events_order_placed": "SELECT COUNT(*) FROM events WHERE event_type = 'order_placed'",
    "events_order_completed": "SELECT COUNT(*) FROM events WHERE event_type = 'order_completed'",
    "events_sla_due": "SELECT COUNT(*) FROM events WHERE event_type = 'sla_due'",
    "overdue_alerts": "SELECT COUNT(*) FROM overdue_alerts",
    "risk_flags_v1": "SELECT COUNT(*) FROM risk_flags WHERE rule_version = 'v1'",
    "clock_date": 'SELECT "current_date" FROM simulation_clock WHERE id = 1',
}

ROWS = [
    ("US order items imported", "order_items"),
    ("US order items excluded (canceled or suspected fraud)", "excluded_items"),
    ("Orders", "orders"),
    ("Orders excluded from evaluation", "excluded_orders"),
    ("Orders used in evaluation", "evaluated_orders"),
    ("First order date", "first_order_date"),
    ("Last order date", "last_order_date"),
    ("Destination states", "states"),
    ("Events: order_placed", "events_order_placed"),
    ("Events: order_completed", "events_order_completed"),
    ("Events: sla_due", "events_sla_due"),
    ("Overdue alerts", "overdue_alerts"),
    ("Risk flags (rule v1)", "risk_flags_v1"),
    ("Simulated clock date", "clock_date"),
]


def collect(conn: psycopg.Connection) -> dict[str, object]:
    values = {}
    with conn.cursor() as cur:
        for name, sql in QUERIES.items():
            cur.execute(sql)
            row = cur.fetchone()
            values[name] = row[0] if row else None
    return values


def format_value(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def build_report(values: dict[str, object]) -> str:
    lines = [
        "# Data summary",
        "",
        "Counts read from the loaded database by `scripts/data_summary.py` "
        "(after `make import`, `make replay` and `make evaluate-risk`).",
        "",
        "| Item | Value |",
        "|---|---|",
    ]
    lines += [f"| {label} | {format_value(values.get(key))} |" for label, key in ROWS]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    apply_env_file(ROOT / ".env", os.environ)
    args = parse_args(argv)
    with connect_owner() as conn:
        conn.read_only = True
        report = build_report(collect(conn))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"saved to {args.out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
