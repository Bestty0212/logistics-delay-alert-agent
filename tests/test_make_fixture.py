"""Tests for scripts/make_fixture.py and the committed synthetic fixture."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from etl.transforms import (
    COLUMNS_KEPT,
    CONSISTENCY_FIELDS,
    DROPPED_COLUMN_NAMES,
    FILTER_COLUMN,
    find_consistency_violations,
    prepare_us_order_items,
    unmapped_state_names,
)
from scripts.make_fixture import (
    END,
    FIXTURE_PATH,
    ORDER_COUNT,
    PERSONAL_COLUMNS,
    PLACEHOLDER,
    RAW_HEADER,
    START,
    build_rows,
    delivery_status,
    main,
    order_date_for,
    parse_args,
    stamp,
    write_fixture,
)
from tests.conftest import ROOT

REAL_CSV = ROOT / "data" / "DataCoSupplyChainDataset.csv"


def test_header_has_kept_dropped_and_filter_columns() -> None:
    assert set(COLUMNS_KEPT) <= set(RAW_HEADER)
    assert set(DROPPED_COLUMN_NAMES) <= set(RAW_HEADER)
    assert FILTER_COLUMN in RAW_HEADER
    assert len(RAW_HEADER) == len(set(RAW_HEADER))


@pytest.mark.skipif(not REAL_CSV.is_file(), reason="real dataset not downloaded")
def test_header_matches_real_csv() -> None:
    real = pd.read_csv(REAL_CSV, encoding="cp1252", nrows=0)
    assert list(real.columns) == RAW_HEADER


def test_delivery_status() -> None:
    assert delivery_status(3, 2) == "Late delivery"
    assert delivery_status(2, 2) == "Shipping on time"
    assert delivery_status(1, 2) == "Advance shipping"


def test_order_dates_span_the_period() -> None:
    assert order_date_for(0) == START
    assert order_date_for(ORDER_COUNT - 1) == END


def test_stamp_uses_raw_format() -> None:
    assert stamp(date(2016, 4, 1), 9, 5) == "4/1/2016 9:05"


def test_build_rows_is_deterministic() -> None:
    assert build_rows(3) == build_rows(3)
    assert build_rows(3) != build_rows(4)


def test_personal_columns_are_placeholders() -> None:
    for row in build_rows():
        assert all(row[column] == PLACEHOLDER for column in PERSONAL_COLUMNS)


def test_rows_pass_the_import_checks() -> None:
    items = prepare_us_order_items(pd.DataFrame(build_rows()))
    assert items["Order Id"].nunique() == ORDER_COUNT
    assert items["is_excluded"].any() and not items["is_excluded"].all()
    assert find_consistency_violations(items, CONSISTENCY_FIELDS) == {}
    assert unmapped_state_names(items["Order State"].unique()) == []
    assert "Nueva York" in set(items["Order State"])


def test_committed_fixture_matches_generator(tmp_path) -> None:
    out = tmp_path / "fixture.csv"
    write_fixture(out, build_rows())
    assert out.read_bytes() == FIXTURE_PATH.read_bytes()


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.out == FIXTURE_PATH
    assert args.seed == 7


def test_main_writes_file(tmp_path, capsys) -> None:
    out = tmp_path / "f.csv"
    assert main(["--out", str(out)]) == 0
    assert list(pd.read_csv(out, encoding="cp1252").columns) == RAW_HEADER
    assert "f.csv" in capsys.readouterr().out
