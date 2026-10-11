"""Pure transforms for US order-item cleaning and order aggregation."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from etl.state_map import STATE_NAME_MAP

US_ORDER_COUNTRY = "Estados Unidos"
EXCLUDED_DELIVERY_STATUS = "Shipping canceled"

# Filter-only; never stored.
FILTER_COLUMN = "Order Country"

COLUMNS_KEPT = [
    "Order Id",
    "Order Item Id",
    "order date (DateOrders)",
    "shipping date (DateOrders)",
    "Days for shipping (real)",
    "Days for shipment (scheduled)",
    "Shipping Mode",
    "Delivery Status",
    "Late_delivery_risk",
    "Order Status",
    "Order State",
    "Department Name",
    "Category Name",
    "Product Name",
    "Product Price",
    "Order Item Quantity",
    "Order Item Discount Rate",
    "Customer Segment",
    "Type",
]

DROPPED_COLUMN_NAMES = [
    "Customer Email",
    "Customer Password",
    "Customer Fname",
    "Customer Lname",
    "Customer Street",
    "Customer Zipcode",
    "Customer City",
    "Customer State",
    "Order Zipcode",
    "Product Description",
    "Product Image",
]

CONSISTENCY_FIELDS = [
    "order date (DateOrders)",
    "Shipping Mode",
    "Days for shipment (scheduled)",
    "Days for shipping (real)",
    "Order State",
    "Delivery Status",
    "Late_delivery_risk",
    "Order Status",
    "Customer Segment",
    "Type",
]

# Fields required by the acceptance consistency check (plus actual_days / extras we also enforce).
ACCEPTANCE_CONSISTENCY_FIELDS = [
    "order date (DateOrders)",
    "Shipping Mode",
    "Days for shipment (scheduled)",
    "Order State",
    "Delivery Status",
    "Late_delivery_risk",
]


def filter_us_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep rows whose destination country is the United States."""
    return df.loc[df[FILTER_COLUMN] == US_ORDER_COUNTRY].copy()


def select_kept_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only columns listed in design section 3 (Order Country already dropped)."""
    missing = [c for c in COLUMNS_KEPT if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing expected columns: {missing}")
    return df.loc[:, COLUMNS_KEPT].copy()


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse raw datetime strings to calendar dates (time of day discarded)."""
    out = df.copy()
    out["order date (DateOrders)"] = pd.to_datetime(
        out["order date (DateOrders)"]
    ).dt.normalize()
    out["shipping date (DateOrders)"] = pd.to_datetime(
        out["shipping date (DateOrders)"]
    ).dt.normalize()
    return out


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add completed_on, sla_due_on, is_excluded, and late_label boolean."""
    out = df.copy()
    out["completed_on"] = out["shipping date (DateOrders)"].dt.date
    out["order_date"] = out["order date (DateOrders)"].dt.date
    scheduled = out["Days for shipment (scheduled)"].astype(int)
    out["sla_due_on"] = (
        out["order date (DateOrders)"] + pd.to_timedelta(scheduled, unit="D")
    ).dt.date
    out["is_excluded"] = out["Delivery Status"] == EXCLUDED_DELIVERY_STATUS
    out["late_label"] = out["Late_delivery_risk"].astype(int).astype(bool)
    return out


def completed_on_real_days_match_pct(df: pd.DataFrame) -> float:
    """
    For non-excluded rows, percent where completed_on - order_date == real days.
    """
    active = df.loc[~df["is_excluded"]]
    if active.empty:
        return 100.0
    delta_days = (
        pd.to_datetime(active["completed_on"]) - pd.to_datetime(active["order_date"])
    ).dt.days
    matches = delta_days == active["Days for shipping (real)"].astype(int)
    return float(matches.mean() * 100.0)


def find_consistency_violations(
    df: pd.DataFrame, fields: Iterable[str] | None = None
) -> dict[str, list[int]]:
    """
    Return field -> list of Order Ids with more than one distinct value.
    Does not choose a value for conflicting orders.
    """
    fields = list(fields if fields is not None else ACCEPTANCE_CONSISTENCY_FIELDS)
    violations: dict[str, list[int]] = {}
    grouped = df.groupby("Order Id", sort=False)
    for field in fields:
        bad = grouped[field].nunique(dropna=False)
        bad_ids = bad[bad > 1].index.astype(int).tolist()
        if bad_ids:
            violations[field] = bad_ids
    return violations


def count_mixed_exclusion_orders(df: pd.DataFrame) -> int:
    """Count Order Ids that contain both excluded and non-excluded items."""
    mixed = df.groupby("Order Id")["is_excluded"].nunique()
    return int((mixed > 1).sum())


def unmapped_state_names(
    states: Iterable[str], mapping: dict[str, str] | None = None
) -> list[str]:
    """Return sorted unique state names missing from the mapping."""
    mapping = mapping if mapping is not None else STATE_NAME_MAP
    missing = {s for s in states if s not in mapping}
    return sorted(missing)


def build_state_names_rows(
    states: Iterable[str], mapping: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """Build (original_name, english_name) rows for states present in the data."""
    mapping = mapping if mapping is not None else STATE_NAME_MAP
    rows = []
    for original in sorted(set(states)):
        if original not in mapping:
            raise ValueError(f"Unmapped state name: {original!r}")
        rows.append((original, mapping[original]))
    return rows


def build_orders_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate item rows to one order row.
    Requires no consistency violations on CONSISTENCY_FIELDS.
    """
    violations = find_consistency_violations(df, CONSISTENCY_FIELDS)
    if violations:
        details = {field: len(ids) for field, ids in violations.items()}
        raise ValueError(
            "Cannot build orders: consistency violations "
            f"(field -> order count): {details}"
        )

    # One row per order; values are unique so first() is deterministic, not a silent pick.
    orders = (
        df.groupby("Order Id", sort=False)
        .agg(
            order_date=("order_date", "first"),
            shipping_mode=("Shipping Mode", "first"),
            scheduled_days=("Days for shipment (scheduled)", "first"),
            actual_days=("Days for shipping (real)", "first"),
            completed_on=("completed_on", "first"),
            sla_due_on=("sla_due_on", "first"),
            order_state=("Order State", "first"),
            delivery_status=("Delivery Status", "first"),
            order_status=("Order Status", "first"),
            late_label=("late_label", "first"),
            is_excluded=("is_excluded", "first"),
            customer_segment=("Customer Segment", "first"),
            payment_type=("Type", "first"),
        )
        .reset_index()
        .rename(columns={"Order Id": "order_id"})
    )
    orders["scheduled_days"] = orders["scheduled_days"].astype(int)
    orders["actual_days"] = orders["actual_days"].astype(int)
    return orders


def build_order_items_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Project item-level columns for order_items."""
    items = pd.DataFrame(
        {
            "order_item_id": df["Order Item Id"].astype(int),
            "order_id": df["Order Id"].astype(int),
            "department_name": df["Department Name"],
            "category_name": df["Category Name"],
            "product_name": df["Product Name"],
            "product_price": df["Product Price"],
            "quantity": df["Order Item Quantity"].astype(int),
            "discount_rate": df["Order Item Discount Rate"],
        }
    )
    return items


def prepare_us_order_items(raw: pd.DataFrame) -> pd.DataFrame:
    """Full item-level pipeline: filter US, keep columns, parse dates, derive fields."""
    us = filter_us_rows(raw)
    kept = select_kept_columns(us)
    dated = parse_dates(kept)
    return add_derived_columns(dated)
