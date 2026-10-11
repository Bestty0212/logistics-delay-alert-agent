"""Tests for the command-line options of import, risk evaluation and data summary scripts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.data_summary import (
    QUERIES,
    REPORT_PATH,
    ROWS,
    build_report,
    collect,
    format_value,
)
from scripts.data_summary import parse_args as summary_args
from scripts.evaluate_risk import REPORT_PATH as RISK_REPORT_PATH
from scripts.evaluate_risk import parse_args as risk_args
from scripts.evaluate_risk import split_count_error
from scripts.import_data import CSV_PATH
from scripts.import_data import parse_args as import_args
from tests.conftest import REAL_DATA_ORDER_COUNT, holds_real_data


def test_import_csv_option() -> None:
    assert import_args([]).csv == CSV_PATH
    assert import_args(["--csv", "x.csv"]).csv == Path("x.csv")


def test_risk_args() -> None:
    defaults = risk_args([])
    assert defaults.expect_orders is None and defaults.report == RISK_REPORT_PATH
    args = risk_args(["--expect-orders", "7887", "--report", "/tmp/r.md"])
    assert args.expect_orders == 7887 and args.report == Path("/tmp/r.md")


def test_split_count_error() -> None:
    assert split_count_error(10, 5, None) is None
    assert split_count_error(10, 5, 15) is None
    assert split_count_error(10, 5, 16) == "training (10) + test (5) != 16 non-excluded orders"


def test_holds_real_data() -> None:
    assert holds_real_data(REAL_DATA_ORDER_COUNT)
    assert not holds_real_data(80)
    assert not holds_real_data(None)


def test_summary_args() -> None:
    assert summary_args([]).out == REPORT_PATH
    assert summary_args(["--out", "s.md"]).out == Path("s.md")


def test_format_value() -> None:
    assert format_value(None) == "n/a"
    assert format_value(24840) == "24,840"
    assert format_value(date(2016, 8, 31)) == "2016-08-31"


def test_rows_cover_every_query() -> None:
    assert {key for _, key in ROWS} == set(QUERIES)


def test_build_report() -> None:
    report = build_report({"orders": 8270, "clock_date": None})
    assert report.startswith("# Data summary\n")
    assert "| Orders | 8,270 |" in report
    assert "| Simulated clock date | n/a |" in report
    assert report.count("\n| ") == len(ROWS) + 1


@pytest.mark.integration
def test_collect_reads_consistent_counts(db_available: bool) -> None:
    if not db_available:
        pytest.skip("database not available")
    from etl.db import connect_owner

    with connect_owner() as conn:
        conn.read_only = True
        values = collect(conn)
    assert set(values) == set(QUERIES)
    assert values["orders"] == values["excluded_orders"] + values["evaluated_orders"]
    assert values["events_order_placed"] == values["orders"]
