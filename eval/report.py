"""Markdown reports: metric tables and a failures file."""

from __future__ import annotations

import json

NA = "n/a"


def pct(value: float | None) -> str:
    return NA if value is None else f"{value * 100:.1f}%"


def num(value: float | None, digits: int = 2) -> str:
    return NA if value is None else f"{value:.{digits}f}"


def usd(value: float | None) -> str:
    return NA if value is None else f"${value:.6f}"


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def run_lines(meta: dict) -> list[str]:
    lines = [
        f"- Run date (real): {meta['run_date']}",
        f"- Mode: {meta['mode']}",
        f"- Model: {meta['model']}",
        f"- Repeats: {meta['repeats']}",
        f"- Simulated clock: {meta['clock_date']}",
        f"- Cost limit: {usd(meta.get('max_cost_usd'))}",
    ]
    if meta.get("aborted"):
        lines.append(f"- **Run aborted:** {meta['abort_reason']}")
    if meta.get("cost_note"):
        lines.append(f"- Cost note: {meta['cost_note']}")
    for note in meta.get("transcript_notes", []):
        lines.append(f"- Transcript not written: {note}")
    return lines


def metric_rows(summary: dict) -> list[list[str]]:
    return [
        ["Answer accuracy", pct(summary["accuracy"])],
        ["Trap pass rate", pct(summary["trap_pass_rate"])],
        ["Tool-call success rate", f"{pct(summary['tool_call_success_rate'])} "
                                   f"({summary['tool_calls']} calls)"],
        ["Average latency per question (s)", num(summary["latency_avg_s"])],
        ["95th-percentile latency (s)", num(summary["latency_p95_s"])],
        ["Average tokens per question", num(summary["tokens_avg"], 0)],
        ["Average cost per question", usd(summary["cost_avg_usd"])],
        ["Total cost", usd(summary["cost_total_usd"])],
        ["Runs that hit the 5-call limit", str(summary["tool_limit_hits"])],
        ["Questions run / total runs", f"{summary['questions']} / {summary['runs']}"],
    ]


def question_rows(results: list[dict]) -> list[list[str]]:
    rows = []
    for r in results:
        failed = ", ".join(c["name"] for c in r["checks"] if not c["passed"]) or "-"
        rows.append([r["id"], r["category"], str(r["repeat"]), "pass" if r["passed"] else "FAIL",
                     failed, num(r["duration_s"]), str(r["total_tokens"]),
                     str(len(r["tool_calls"])), r["stop"]])
    return rows


def build_summary_report(summary: dict, results: list[dict], meta: dict) -> str:
    lines = [f"# Agent evaluation {meta['run_date']}", "", *run_lines(meta), "", "## Metrics", ""]
    lines += table(["Metric", "Value"], metric_rows(summary))
    lines += ["", "## Accuracy by category", ""]
    lines += table(
        ["Category", "Passed", "Runs", "Accuracy"],
        [[c, str(v["passed"]), str(v["total"]), pct(v["accuracy"])]
         for c, v in summary["by_category"].items()],
    )
    lines += ["", "## Pass rate by check", ""]
    lines += table(["Check", "Pass rate"],
                   [[k, pct(v)] for k, v in summary["check_pass_rates"].items()])
    if meta["repeats"] > 1:
        lines += ["", "## Stability across repeats", "",
                  f"- Questions whose pass/fail changed: {summary['outcome_changed']}",
                  f"- Questions whose answer text changed: {summary['answer_changed']}", ""]
        lines += table(
            ["Question", "Runs", "Passes", "Pass/fail changed", "Text changed"],
            [[q, str(s["runs"]), str(s["passes"]), str(s["outcome_changed"]),
              str(s["answer_changed"])] for q, s in summary["stability"].items()],
        )
    lines += ["", "## Per question", ""]
    lines += table(["Id", "Category", "Repeat", "Result", "Failed checks", "Latency (s)",
                    "Tokens", "Tool calls", "Stop"], question_rows(results))
    return "\n".join(lines) + "\n"


def tool_call_lines(tool_calls: list[dict]) -> list[str]:
    if not tool_calls:
        return ["- (no tool calls)"]
    return [
        f"- `{c['name']}({json.dumps(c['arguments'], ensure_ascii=False, default=str)})` -> "
        + ("ok" if c.get("ok") else f"error {c.get('error_code')}")
        for c in tool_calls
    ]


def failure_section(result: dict, gold_entry: dict) -> list[str]:
    lines = [
        f"## {result['id']} ({result['category']}, repeat {result['repeat']})",
        "",
        f"**Question:** {result['question']}  ",
        f"**As of:** {result['as_of']}",
        "",
        "**Failed checks:**",
    ]
    lines += [f"- {c['name']}: {c['detail']}" for c in result["checks"] if not c["passed"]]
    lines += ["", "**Gold values:** `" + json.dumps(gold_entry.get("values", {})) + "`"]
    if gold_entry.get("sql"):
        lines += ["", "**Gold SQL:**", "", "```sql", gold_entry["sql"], "```",
                  f"Parameters: `{json.dumps(gold_entry.get('params', {}))}`"]
    else:
        lines += [f"Gold note: {gold_entry.get('note', '')}"]
    lines += ["", "**Agent answer:**", "", "> " + result["answer"].replace("\n", "\n> "), "",
              "**Tool calls:**", *tool_call_lines(result["tool_calls"]), ""]
    return lines


def build_failures_report(results: list[dict], gold: dict, meta: dict) -> str:
    failed = [r for r in results if not r["passed"]]
    lines = [f"# Agent evaluation failures {meta['run_date']}", "", *run_lines(meta), "",
             f"{len(failed)} failed of {len(results)} runs.", ""]
    for result in failed:
        lines += failure_section(result, gold["entries"].get(result["id"], {}))
    return "\n".join(lines) + "\n"
