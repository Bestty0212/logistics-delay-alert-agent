"""Token cost from config/pricing.json (prices filled in by the user; never guessed)."""

from __future__ import annotations

import json
from pathlib import Path

PRICING_PATH = Path(__file__).resolve().parents[1] / "config" / "pricing.json"
MISSING_PRICES_NOTE = "prices missing in config/pricing.json; reporting tokens only"


def load_pricing(path: Path = PRICING_PATH) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def model_prices(pricing: dict, model: str) -> tuple[float, float] | None:
    entry = pricing.get("models", {}).get(model) or {}
    input_price = entry.get("input_per_million")
    output_price = entry.get("output_per_million")
    if not isinstance(input_price, (int, float)) or not isinstance(output_price, (int, float)):
        return None
    return float(input_price), float(output_price)


def estimate_cost(pricing: dict, model: str, input_tokens: int, output_tokens: int) -> dict:
    prices = model_prices(pricing, model)
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if prices is None:
        return {**usage, "cost_usd": None, "note": MISSING_PRICES_NOTE}
    cost = (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000
    return {**usage, "cost_usd": round(cost, 6), "note": None}
