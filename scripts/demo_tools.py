#!/usr/bin/env python3
"""Call each agent tool as of 2016-06-30 and as of the simulated clock; print JSON."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_tools.registry import call_tool  # noqa: E402
from etl.env import apply_env_file  # noqa: E402

DEMO_AS_OF = "2016-06-30"


def show(name: str, arguments: dict) -> dict:
    result = call_tool(name, arguments)
    print(f"\n>>> {name}({json.dumps(arguments)})")
    print(json.dumps(result, indent=2))
    return result


def first_order_ids(result: dict) -> tuple[int | None, int | None]:
    """First overdue and first not-yet-overdue order from a list result."""
    orders = result.get("data", {}).get("orders", []) if result.get("ok") else []
    overdue = next((o["order_id"] for o in orders if o["overdue"]), None)
    pending = next((o["order_id"] for o in orders if not o["overdue"]), None)
    return overdue, pending


def demo_as_of(as_of: str | None) -> None:
    label = as_of or "simulated clock (default)"
    print(f"\n========== as of {label} ==========")
    base = {"as_of": as_of} if as_of else {}
    show("list_at_risk_orders", {**base, "limit": 5})
    show("list_at_risk_orders", {**base, "state": "New York", "limit": 5})
    show("get_shipping_mode_stats", base)
    show("get_shipping_mode_stats", {**base, "state": "New York"})
    overdue_id, pending_id = first_order_ids(
        call_tool("list_at_risk_orders", {**base, "limit": 50})
    )
    for order_id in filter(None, (overdue_id, pending_id)):
        show("get_order_timeline", {**base, "order_id": order_id})
        show("draft_notification", {**base, "order_id": order_id})


def main() -> int:
    apply_env_file(ROOT / ".env", os.environ)
    demo_as_of(DEMO_AS_OF)
    demo_as_of(None)
    print("\n========== error examples ==========")
    show("get_order_timeline", {"order_id": 99999999})
    show("list_at_risk_orders", {"state": "Atlantis"})
    show("list_at_risk_orders", {"limit": 500})
    show("get_shipping_mode_stats", {"as_of": "2030-01-01"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
