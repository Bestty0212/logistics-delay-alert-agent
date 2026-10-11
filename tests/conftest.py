"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.env import apply_env_file

apply_env_file(ROOT / ".env", os.environ)


def make_sample_items() -> pd.DataFrame:
    """Tiny in-memory sample with two orders (one multi-item, one excluded)."""
    return pd.DataFrame(
        {
            "Type": ["DEBIT", "DEBIT", "TRANSFER"],
            "Days for shipping (real)": [2, 2, 0],
            "Days for shipment (scheduled)": [1, 1, 0],
            "Delivery Status": ["Late delivery", "Late delivery", "Shipping canceled"],
            "Late_delivery_risk": [1, 1, 0],
            "Category Name": ["Tech", "Tech", "Books"],
            "Customer Segment": ["Consumer", "Consumer", "Corporate"],
            "Department Name": ["Fan Shop", "Fan Shop", "Book Shop"],
            "Order Country": ["Estados Unidos", "Estados Unidos", "Estados Unidos"],
            "order date (DateOrders)": [
                "4/1/2016 0:00",
                "4/1/2016 0:00",
                "4/2/2016 12:30",
            ],
            "Order Id": [100, 100, 200],
            "Order Item Discount Rate": [0.1, 0.2, 0.0],
            "Order Item Id": [1, 2, 3],
            "Order Item Quantity": [1, 2, 1],
            "Order State": ["Nueva York", "Nueva York", "California"],
            "Order Status": ["COMPLETE", "COMPLETE", "CANCELED"],
            "Product Name": ["A", "B", "C"],
            "Product Price": [10.0, 20.0, 5.0],
            "shipping date (DateOrders)": [
                "4/3/2016 0:00",
                "4/3/2016 0:00",
                "4/2/2016 12:30",
            ],
            "Shipping Mode": ["First Class", "First Class", "Same Day"],
            "Customer Email": ["x@example.com", "x@example.com", "y@example.com"],
        }
    )


@pytest.fixture
def sample_raw() -> pd.DataFrame:
    return make_sample_items()


@pytest.fixture(scope="session")
def db_available() -> bool:
    try:
        from etl.db import connect_owner

        with connect_owner() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False


REAL_DATA_ORDER_COUNT = 8270


def holds_real_data(order_count: int | None) -> bool:
    """The real US subset has exactly 8,270 orders; the CI fixture has far fewer."""
    return order_count == REAL_DATA_ORDER_COUNT


@pytest.fixture(scope="session")
def real_data_loaded(db_available: bool) -> bool:
    if not db_available:
        return False
    from etl.db import connect_owner

    try:
        with connect_owner() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orders")
            return holds_real_data(cur.fetchone()[0])
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _skip_real_data_tests(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("real_data") and not request.getfixturevalue(
        "real_data_loaded"
    ):
        pytest.skip("needs the real DataCo dataset loaded (counts are dataset-specific)")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: tests that need PostgreSQL")
    config.addinivalue_line(
        "markers", "real_data: tests whose expected values only hold for the real dataset"
    )
