"""Unit tests for ETL transform functions."""

from __future__ import annotations

import pandas as pd
import pytest

from etl.env import apply_env_file, load_env_file
from etl.state_map import STATE_NAME_MAP
from etl.transforms import (
    COLUMNS_KEPT,
    DROPPED_COLUMN_NAMES,
    build_order_items_frame,
    build_orders_frame,
    build_state_names_rows,
    completed_on_real_days_match_pct,
    count_mixed_exclusion_orders,
    filter_us_rows,
    find_consistency_violations,
    parse_dates,
    prepare_us_order_items,
    select_kept_columns,
    unmapped_state_names,
)


def test_filter_us_rows_keeps_only_estados_unidos(sample_raw: pd.DataFrame) -> None:
    mixed = pd.concat(
        [
            sample_raw,
            sample_raw.iloc[[0]].assign(**{"Order Country": "México"}),
        ],
        ignore_index=True,
    )
    out = filter_us_rows(mixed)
    assert len(out) == 3
    assert (out["Order Country"] == "Estados Unidos").all()


def test_select_kept_columns_drops_privacy_and_extras(sample_raw: pd.DataFrame) -> None:
    us = filter_us_rows(sample_raw)
    kept = select_kept_columns(us)
    assert list(kept.columns) == COLUMNS_KEPT
    for name in DROPPED_COLUMN_NAMES:
        assert name not in kept.columns
    assert "Order Country" not in kept.columns
    assert "Customer Email" not in kept.columns


def test_select_kept_columns_missing_raises(sample_raw: pd.DataFrame) -> None:
    bad = sample_raw.drop(columns=["Product Price"])
    with pytest.raises(ValueError, match="missing expected columns"):
        select_kept_columns(filter_us_rows(bad))


def test_parse_dates_discards_time_of_day(sample_raw: pd.DataFrame) -> None:
    kept = select_kept_columns(filter_us_rows(sample_raw))
    dated = parse_dates(kept)
    assert dated["order date (DateOrders)"].dt.hour.eq(0).all()
    assert dated["shipping date (DateOrders)"].dt.hour.eq(0).all()


def test_add_derived_columns_and_match_pct(sample_raw: pd.DataFrame) -> None:
    items = prepare_us_order_items(sample_raw)
    assert items.loc[items["Order Id"] == 100, "is_excluded"].eq(False).all()
    assert items.loc[items["Order Id"] == 200, "is_excluded"].eq(True).all()
    assert items.loc[items["Order Id"] == 100, "late_label"].eq(True).all()
    # order 100: completed 2016-04-03, ordered 2016-04-01, real days 2
    assert completed_on_real_days_match_pct(items) == 100.0
    row100 = items.loc[items["Order Id"] == 100].iloc[0]
    assert row100["sla_due_on"].isoformat() == "2016-04-02"


def test_find_consistency_violations_detects_conflict(sample_raw: pd.DataFrame) -> None:
    items = prepare_us_order_items(sample_raw)
    items.loc[items["Order Item Id"] == 2, "Shipping Mode"] = "Second Class"
    violations = find_consistency_violations(items, ["Shipping Mode"])
    assert violations["Shipping Mode"] == [100]


def test_count_mixed_exclusion_orders(sample_raw: pd.DataFrame) -> None:
    items = prepare_us_order_items(sample_raw)
    assert count_mixed_exclusion_orders(items) == 0
    mixed = items.copy()
    mixed.loc[mixed["Order Item Id"] == 2, "is_excluded"] = True
    assert count_mixed_exclusion_orders(mixed) == 1


def test_unmapped_and_build_state_names() -> None:
    assert unmapped_state_names(["Nueva York", "California"]) == []
    assert unmapped_state_names(["Nueva York", "Atlantis"]) == ["Atlantis"]
    rows = build_state_names_rows(["Nueva York", "California"])
    assert ("Nueva York", "New York") in rows
    assert ("California", "California") in rows
    with pytest.raises(ValueError, match="Unmapped"):
        build_state_names_rows(["Atlantis"])


def test_build_orders_and_items(sample_raw: pd.DataFrame) -> None:
    from scripts.import_data import null_fields_for_excluded_orders

    items = prepare_us_order_items(sample_raw)
    orders = null_fields_for_excluded_orders(build_orders_frame(items))
    assert len(orders) == 2
    assert set(orders["order_id"]) == {100, 200}
    order100 = orders.loc[orders["order_id"] == 100].iloc[0]
    assert order100["shipping_mode"] == "First Class"
    assert bool(order100["is_excluded"]) is False
    assert order100["completed_on"] is not None
    assert bool(order100["late_label"]) is True
    order200 = orders.loc[orders["order_id"] == 200].iloc[0]
    assert bool(order200["is_excluded"]) is True
    assert order200["completed_on"] is None
    assert order200["late_label"] is None

    order_items = build_order_items_frame(items)
    assert len(order_items) == 3
    assert list(order_items.columns) == [
        "order_item_id",
        "order_id",
        "department_name",
        "category_name",
        "product_name",
        "product_price",
        "quantity",
        "discount_rate",
    ]


def test_build_orders_refuses_inconsistent(sample_raw: pd.DataFrame) -> None:
    items = prepare_us_order_items(sample_raw)
    items.loc[items["Order Item Id"] == 2, "Shipping Mode"] = "Second Class"
    with pytest.raises(ValueError, match="consistency violations"):
        build_orders_frame(items)


def test_state_map_covers_sample_keys() -> None:
    assert STATE_NAME_MAP["Nueva York"] == "New York"
    assert STATE_NAME_MAP["Oregón"] == "Oregon"


def test_load_env_file(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text("FOO=bar\n# comment\nBAZ='qux'\n", encoding="utf-8")
    assert load_env_file(path) == {"FOO": "bar", "BAZ": "qux"}
    env: dict[str, str] = {"FOO": "existing"}
    apply_env_file(path, env)
    assert env["FOO"] == "existing"
    assert env["BAZ"] == "qux"
