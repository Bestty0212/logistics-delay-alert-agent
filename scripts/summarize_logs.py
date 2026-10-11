#!/usr/bin/env python3
"""Summarize logs/agent_calls.jsonl: questions, error and fallback rates, retries, latency, tokens, cost."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.call_log import LOG_PATH  # noqa: E402
from agent.loop import (  # noqa: E402
    MODEL_ERROR_MESSAGE,
    NO_ANSWER_MESSAGE,
    TOKEN_BUDGET_MESSAGE,
    TOOL_LIMIT_MESSAGE,
)

FALLBACK_MESSAGES = frozenset(
    {MODEL_ERROR_MESSAGE, NO_ANSWER_MESSAGE, TOKEN_BUDGET_MESSAGE, TOOL_LIMIT_MESSAGE}
)


def read_entries(path: Path) -> tuple[list[dict], int]:
    """Parsed log lines and the number of malformed lines skipped."""
    entries, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(entry, dict):
            entries.append(entry)
        else:
            bad += 1
    return entries, bad


def is_error(entry: dict) -> bool:
    return bool(entry.get("error_class") or entry.get("model_error"))


def is_fallback(entry: dict) -> bool:
    """Uses the logged flag when present; older lines are judged by the fixed messages."""
    if "fallback" in entry:
        return bool(entry["fallback"])
    return entry.get("final_answer") in FALLBACK_MESSAGES


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(pct / 100 * len(ordered))) - 1]


def rate(count: int, total: int) -> float | None:
    return count / total if total else None


def summarize(entries: list[dict]) -> dict:
    total = len(entries)
    retries = [int(e.get("retry_count") or 0) for e in entries]
    latencies = [float(e["total_duration_s"]) for e in entries
                 if isinstance(e.get("total_duration_s"), (int, float))]
    tokens = [int(e.get("input_tokens") or 0) + int(e.get("output_tokens") or 0) for e in entries]
    costs = [e.get("cost_usd") for e in entries]
    calls = [c for e in entries for c in e.get("tool_calls") or []]
    known_costs = total > 0 and all(isinstance(c, (int, float)) for c in costs)
    return {
        "questions": total,
        "error_rate": rate(sum(is_error(e) for e in entries), total),
        "fallback_rate": rate(sum(is_fallback(e) for e in entries), total),
        "retries_total": sum(retries),
        "questions_with_retries": sum(r > 0 for r in retries),
        "retries_max": max(retries, default=0),
        "tool_calls": len(calls),
        "tool_call_error_rate": rate(sum(not c.get("ok") for c in calls), len(calls)),
        "latency_p50_s": percentile(latencies, 50),
        "latency_p95_s": percentile(latencies, 95),
        "tokens_total": sum(tokens),
        "tokens_avg": rate(sum(tokens), total),
        "cost_total_usd": sum(costs) if known_costs else None,
        "cost_avg_usd": rate(sum(costs), total) if known_costs else None,
    }


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def fmt_num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def format_summary(summary: dict, skipped: int) -> str:
    cost_total = summary["cost_total_usd"]
    cost_avg = summary["cost_avg_usd"]
    lines = [
        f"questions:            {summary['questions']}",
        f"error rate:           {fmt_pct(summary['error_rate'])}",
        f"fallback rate:        {fmt_pct(summary['fallback_rate'])}",
        f"retries:              {summary['retries_total']} total, "
        f"{summary['questions_with_retries']} questions retried, max {summary['retries_max']}",
        f"tool calls:           {summary['tool_calls']} "
        f"(error rate {fmt_pct(summary['tool_call_error_rate'])})",
        f"latency p50 / p95:    {fmt_num(summary['latency_p50_s'])} s / "
        f"{fmt_num(summary['latency_p95_s'])} s",
        f"tokens:               {summary['tokens_total']} total, "
        f"{fmt_num(summary['tokens_avg'], 0)} per question",
        "cost:                 "
        + ("n/a (some prices missing)" if cost_total is None
           else f"${cost_total:.6f} total, ${cost_avg:.6f} per question"),
    ]
    if skipped:
        lines.append(f"malformed lines skipped: {skipped}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=LOG_PATH, help="log file (JSON lines)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.path.is_file():
        print(f"no log file at {args.path.name}; ask a question first", file=sys.stderr)
        return 1
    entries, skipped = read_entries(args.path)
    print(format_summary(summarize(entries), skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
