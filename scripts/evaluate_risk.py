#!/usr/bin/env python3
"""Compute rule v1 flags, write them to risk_flags, and evaluate on the test period."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.db import connect_owner  # noqa: E402
from etl.env import apply_env_file  # noqa: E402
from etl.risk import (  # noqa: E402
    build_flag_rows,
    build_report,
    compute_mode_late_rates,
    evaluate_rule_and_baselines,
    evaluation_orders,
    per_mode_table,
    threshold_sensitivity,
    training_orders,
)
from etl.risk_db import load_orders_frame, write_flags  # noqa: E402

ENV_PATH = ROOT / ".env"
REPORT_PATH = ROOT / "reports" / "risk_eval_v1.md"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-orders", type=int,
                        help="fail unless training + test orders equal this (7887 for the real data)")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args(argv)


def split_count_error(train: int, test: int, expected: int | None) -> str | None:
    if expected is None or train + test == expected:
        return None
    return f"training ({train}) + test ({test}) != {expected} non-excluded orders"


def main(argv: list[str] | None = None) -> int:
    apply_env_file(ENV_PATH, os.environ)
    args = parse_args(argv)

    with connect_owner() as conn:
        orders = load_orders_frame(conn)

        training = training_orders(orders)
        evaluated = evaluation_orders(orders)
        problem = split_count_error(len(training), len(evaluated), args.expect_orders)
        if problem:
            print(f"ERROR: {problem}", file=sys.stderr)
            return 1

        rates = compute_mode_late_rates(orders)
        flag_rows = build_flag_rows(orders, rates)
        write_flags(conn, flag_rows)

    flagged_ids = {order_id for order_id, _, _ in flag_rows}
    excluded_ids = set(orders.loc[orders["is_excluded"], "order_id"])

    report = build_report(
        train_count=len(training),
        test_count=len(evaluated),
        train_mode_counts=training["shipping_mode"].value_counts().to_dict(),
        mode_late_rates=rates,
        in_sample=evaluate_rule_and_baselines(training, rates),
        test_results=evaluate_rule_and_baselines(evaluated, rates),
        mode_rows=per_mode_table(evaluated, rates),
        sensitivity=threshold_sensitivity(evaluated, rates),
        flags_written=len(flag_rows),
        excluded_flagged=len(flagged_ids & excluded_ids),
        last_order_date=orders["order_date"].max(),
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"report saved to {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
