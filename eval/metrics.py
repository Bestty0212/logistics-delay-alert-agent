"""Metrics over per-question eval results (one result dict per question per repeat)."""

from __future__ import annotations

import math
from collections import defaultdict

from eval.gold import CATEGORIES


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def accuracy(results: list[dict]) -> float | None:
    return ratio(sum(r["passed"] for r in results), len(results))


def accuracy_by_category(results: list[dict]) -> dict[str, dict]:
    table = {}
    for category in CATEGORIES:
        subset = [r for r in results if r["category"] == category]
        table[category] = {
            "passed": sum(r["passed"] for r in subset),
            "total": len(subset),
            "accuracy": accuracy(subset),
        }
    return table


def tool_call_success_rate(results: list[dict]) -> float | None:
    calls = [c for r in results for c in r["tool_calls"]]
    return ratio(sum(bool(c.get("ok")) for c in calls), len(calls))


def average_cost(results: list[dict]) -> float | None:
    """None when any cost is unknown (prices missing), so a partial sum is never shown."""
    costs = [r["cost_usd"] for r in results]
    if not costs or any(c is None for c in costs):
        return None
    return average(costs)


def check_pass_rates(results: list[dict]) -> dict[str, float | None]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for result in results:
        for check in result["checks"]:
            counts[check["name"]][0] += check["passed"]
            counts[check["name"]][1] += 1
    return {name: ratio(p, t) for name, (p, t) in sorted(counts.items())}


def stability(results: list[dict]) -> dict[str, dict]:
    """Per question across repeats: runs, passes, and whether pass/fail or answer text changed."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        grouped[result["id"]].append(result)
    return {
        qid: {
            "runs": len(runs),
            "passes": sum(r["passed"] for r in runs),
            "outcome_changed": len({r["passed"] for r in runs}) > 1,
            "answer_changed": len({r["answer"] for r in runs}) > 1,
        }
        for qid, runs in grouped.items()
    }


def summarize(results: list[dict]) -> dict:
    latencies = [r["duration_s"] for r in results]
    stable = stability(results)
    traps = [r for r in results if r["category"] == "trap"]
    return {
        "runs": len(results),
        "questions": len(stable),
        "accuracy": accuracy(results),
        "by_category": accuracy_by_category(results),
        "trap_pass_rate": accuracy(traps),
        "tool_call_success_rate": tool_call_success_rate(results),
        "tool_calls": sum(len(r["tool_calls"]) for r in results),
        "latency_avg_s": average(latencies),
        "latency_p95_s": percentile(latencies, 95),
        "tokens_avg": average([r["total_tokens"] for r in results]),
        "cost_avg_usd": average_cost(results),
        "cost_total_usd": sum(r["cost_usd"] for r in results)
        if results and all(r["cost_usd"] is not None for r in results) else None,
        "tool_limit_hits": sum(r["hit_tool_limit"] for r in results),
        "check_pass_rates": check_pass_rates(results),
        "stability": stable,
        "outcome_changed": sum(s["outcome_changed"] for s in stable.values()),
        "answer_changed": sum(s["answer_changed"] for s in stable.values()),
    }
