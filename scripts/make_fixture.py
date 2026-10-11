#!/usr/bin/env python3
"""Generate tests/fixtures/synthetic_dataco.csv: made-up orders in the real DataCo CSV layout.

Used by CI instead of the real dataset (which is never committed). Every value is invented
and personal-data columns hold placeholders; only the column names come from the real file.
Deterministic: the same seed always produces the same file.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "synthetic_dataco.csv"
SEED = 7
ORDER_COUNT = 80
FIRST_ORDER_ID = 1001
START = date(2016, 4, 1)
END = date(2016, 8, 25)
PLACEHOLDER = "XXXXXXXXX"

# Copied from the header of the real DataCoSupplyChainDataset.csv (not typed from memory).
RAW_HEADER = [
    "Type", "Days for shipping (real)", "Days for shipment (scheduled)", "Benefit per order",
    "Sales per customer", "Delivery Status", "Late_delivery_risk", "Category Id",
    "Category Name", "Customer City", "Customer Country", "Customer Email", "Customer Fname",
    "Customer Id", "Customer Lname", "Customer Password", "Customer Segment", "Customer State",
    "Customer Street", "Customer Zipcode", "Department Id", "Department Name", "Latitude",
    "Longitude", "Market", "Order City", "Order Country", "Order Customer Id",
    "order date (DateOrders)", "Order Id", "Order Item Cardprod Id", "Order Item Discount",
    "Order Item Discount Rate", "Order Item Id", "Order Item Product Price",
    "Order Item Profit Ratio", "Order Item Quantity", "Sales", "Order Item Total",
    "Order Profit Per Order", "Order Region", "Order State", "Order Status", "Order Zipcode",
    "Product Card Id", "Product Category Id", "Product Description", "Product Image",
    "Product Name", "Product Price", "Product Status", "shipping date (DateOrders)",
    "Shipping Mode",
]

PERSONAL_COLUMNS = (
    "Customer Email", "Customer Fname", "Customer Lname", "Customer Password",
    "Customer Street", "Customer City", "Customer State", "Customer Zipcode", "Order Zipcode",
)

# shipping mode -> (scheduled days, possible real days)
MODES = {
    "First Class": (1, [2]),
    "Second Class": (2, [2, 3, 4, 4]),
    "Standard Class": (4, [2, 3, 4, 5, 6]),
    "Same Day": (0, [0, 1]),
}
STATES = ["California", "Nueva York", "Texas", "Florida", "Ohio", "Illinois", "Michigan",
          "Massachusetts"]
PAYMENT_TYPES = ["DEBIT", "TRANSFER", "CASH", "PAYMENT"]
SEGMENTS = ["Consumer", "Corporate", "Home Office"]
OPEN_STATUSES = ["COMPLETE", "PENDING", "CLOSED", "PROCESSING"]
EXCLUDED_STATUSES = ["CANCELED", "SUSPECTED_FRAUD"]
DEPARTMENTS = [("Fan Shop", "Camping & Hiking"), ("Apparel", "Cleats"), ("Golf", "Golf Balls")]


def delivery_status(real: int, scheduled: int) -> str:
    if real > scheduled:
        return "Late delivery"
    if real == scheduled:
        return "Shipping on time"
    return "Advance shipping"


def order_date_for(index: int) -> date:
    span = (END - START).days
    return START + timedelta(days=index * span // (ORDER_COUNT - 1))


def stamp(day: date, hour: int, minute: int) -> str:
    return f"{day.month}/{day.day}/{day.year} {hour}:{minute:02d}"


def base_row() -> dict[str, object]:
    row: dict[str, object] = {column: 0 for column in RAW_HEADER}
    row.update({column: PLACEHOLDER for column in PERSONAL_COLUMNS})
    row.update({"Product Description": "", "Product Image": "", "Market": "USCA",
                "Order Region": "West of USA", "Order City": "Synthetic City",
                "Customer Country": "EE. UU.", "Order Country": "Estados Unidos"})
    return row


def order_fields(rng: random.Random, order_id: int, index: int) -> dict[str, object]:
    mode = rng.choice(list(MODES))
    scheduled, real_choices = MODES[mode]
    real = rng.choice(real_choices)
    excluded = rng.random() < 0.1
    placed = order_date_for(index)
    hour, minute = rng.randrange(24), rng.randrange(60)
    return {
        "Order Id": order_id,
        "Order Customer Id": order_id,
        "Customer Id": order_id,
        "Shipping Mode": mode,
        "Days for shipment (scheduled)": scheduled,
        "Days for shipping (real)": real,
        "Delivery Status": "Shipping canceled" if excluded else delivery_status(real, scheduled),
        "Late_delivery_risk": 0 if excluded else int(real > scheduled),
        "Order Status": rng.choice(EXCLUDED_STATUSES if excluded else OPEN_STATUSES),
        "order date (DateOrders)": stamp(placed, hour, minute),
        "shipping date (DateOrders)": stamp(placed + timedelta(days=real), hour, minute),
        "Order State": STATES[index % len(STATES)],
        "Type": rng.choice(PAYMENT_TYPES),
        "Customer Segment": rng.choice(SEGMENTS),
    }


def item_fields(rng: random.Random, item_id: int) -> dict[str, object]:
    department, category = rng.choice(DEPARTMENTS)
    price = round(rng.uniform(10, 300), 2)
    quantity = rng.randint(1, 4)
    return {
        "Order Item Id": item_id,
        "Department Name": department,
        "Category Name": category,
        "Product Name": f"Synthetic product {item_id % 17}",
        "Product Price": price,
        "Order Item Product Price": price,
        "Order Item Quantity": quantity,
        "Order Item Discount Rate": rng.choice([0.0, 0.05, 0.1, 0.25]),
        "Sales": round(price * quantity, 2),
    }


def build_rows(seed: int = SEED) -> list[dict[str, object]]:
    rng = random.Random(seed)
    rows, item_id = [], 1
    for index in range(ORDER_COUNT):
        order = order_fields(rng, FIRST_ORDER_ID + index, index)
        for _ in range(rng.randint(1, 3)):
            rows.append({**base_row(), **order, **item_fields(rng, item_id)})
            item_id += 1
    foreign = {**base_row(), **order_fields(rng, FIRST_ORDER_ID + ORDER_COUNT, 0),
               **item_fields(rng, item_id), "Order Country": "Francia", "Order State": "Ile-de-France"}
    rows.append(foreign)
    return rows


def write_fixture(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="cp1252") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--seed", type=int, default=SEED)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = build_rows(args.seed)
    write_fixture(args.out, rows)
    print(f"wrote {len(rows)} synthetic rows to {args.out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
