#!/usr/bin/env python3
"""Import cleaned US DataCo orders into PostgreSQL."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.db import connect_owner  # noqa: E402
from etl.env import apply_env_file  # noqa: E402
from etl.transforms import (  # noqa: E402
    ACCEPTANCE_CONSISTENCY_FIELDS,
    build_order_items_frame,
    build_orders_frame,
    build_state_names_rows,
    completed_on_real_days_match_pct,
    count_mixed_exclusion_orders,
    find_consistency_violations,
    prepare_us_order_items,
    unmapped_state_names,
)

CSV_PATH = ROOT / "data" / "DataCoSupplyChainDataset.csv"
ENV_PATH = ROOT / ".env"


def read_raw_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="cp1252", low_memory=False)


def clear_tables(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE TABLE risk_flags, events, order_items, orders, state_names "
            "RESTART IDENTITY CASCADE"
        )
    conn.commit()


def insert_state_names(conn: psycopg.Connection, rows: list[tuple[str, str]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO state_names (original_name, english_name) VALUES (%s, %s)",
            rows,
        )
    conn.commit()


def null_fields_for_excluded_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Set completed_on and late_label to NULL for excluded orders."""
    out = orders.copy()
    excluded = out["is_excluded"].astype(bool)
    out["completed_on"] = out["completed_on"].astype(object)
    out["late_label"] = out["late_label"].astype(object)
    out.loc[excluded, "completed_on"] = None
    out.loc[excluded, "late_label"] = None
    return out


def insert_orders(conn: psycopg.Connection, orders: pd.DataFrame) -> None:
    records = []
    for r in orders.itertuples(index=False):
        is_excluded = bool(r.is_excluded)
        if is_excluded:
            completed_on = None
            late_label = None
        else:
            completed_on = r.completed_on
            late_label = bool(r.late_label)
        records.append(
            (
                int(r.order_id),
                r.order_date,
                r.shipping_mode,
                int(r.scheduled_days),
                int(r.actual_days),
                completed_on,
                r.sla_due_on,
                r.order_state,
                r.delivery_status,
                r.order_status,
                late_label,
                is_excluded,
                r.customer_segment,
                r.payment_type,
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO orders (
                order_id, order_date, shipping_mode, scheduled_days, actual_days,
                completed_on, sla_due_on, order_state, delivery_status, order_status,
                late_label, is_excluded, customer_segment, payment_type
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            """,
            records,
        )
    conn.commit()


def insert_order_items(conn: psycopg.Connection, items: pd.DataFrame) -> None:
    records = [
        (
            int(r.order_item_id),
            int(r.order_id),
            r.department_name,
            r.category_name,
            r.product_name,
            r.product_price,
            int(r.quantity),
            r.discount_rate,
        )
        for r in items.itertuples(index=False)
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO order_items (
                order_item_id, order_id, department_name, category_name,
                product_name, product_price, quantity, discount_rate
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            records,
        )
    conn.commit()


def print_report(
    *,
    item_count: int,
    order_count: int,
    excluded_items: int,
    non_excluded_items: int,
    match_pct: float,
    violations: dict[str, list[int]],
    mixed_orders: int,
    unmapped: list[str],
) -> None:
    print(f"order items imported: {item_count}")
    print(f"orders: {order_count}")
    print(f"excluded items: {excluded_items}")
    print(f"non-excluded items: {non_excluded_items}")
    print(f"completed_on vs real-days match (non-excluded): {match_pct:.2f}%")
    if violations:
        print("consistency violations:")
        for field, order_ids in violations.items():
            print(f"  {field}: {len(order_ids)} orders")
    else:
        print("consistency violations: 0")
    print(f"orders with both excluded and non-excluded items: {mixed_orders}")
    if unmapped:
        print("unmapped state names:")
        for name in unmapped:
            print(f"  {name}")
    else:
        print("unmapped state names: 0")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=CSV_PATH,
                        help="DataCo CSV (default: data/DataCoSupplyChainDataset.csv)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    apply_env_file(ENV_PATH, os.environ)
    csv_path = parse_args(argv).csv

    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    raw = read_raw_csv(csv_path)
    items = prepare_us_order_items(raw)

    match_pct = completed_on_real_days_match_pct(items)
    violations = find_consistency_violations(items, ACCEPTANCE_CONSISTENCY_FIELDS)
    mixed_orders = count_mixed_exclusion_orders(items)
    unmapped = unmapped_state_names(items["Order State"].unique())

    excluded_items = int(items["is_excluded"].sum())
    non_excluded_items = int((~items["is_excluded"]).sum())

    print_report(
        item_count=len(items),
        order_count=int(items["Order Id"].nunique()),
        excluded_items=excluded_items,
        non_excluded_items=non_excluded_items,
        match_pct=match_pct,
        violations=violations,
        mixed_orders=mixed_orders,
        unmapped=unmapped,
    )

    if unmapped:
        print("Aborting import: unmapped state names present.", file=sys.stderr)
        return 1
    if violations:
        print(
            "Aborting import: consistency violations present; refusing to pick values.",
            file=sys.stderr,
        )
        return 1

    state_rows = build_state_names_rows(items["Order State"].unique())
    orders = null_fields_for_excluded_orders(build_orders_frame(items))
    order_items = build_order_items_frame(items)

    with connect_owner() as conn:
        clear_tables(conn)
        insert_state_names(conn, state_rows)
        insert_orders(conn, orders)
        insert_order_items(conn, order_items)

    print("import complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
