"""Tests for scripts/summarize_logs.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.loop import MODEL_ERROR_MESSAGE
from scripts.summarize_logs import (
    fmt_num,
    fmt_pct,
    format_summary,
    is_error,
    is_fallback,
    main,
    parse_args,
    percentile,
    rate,
    read_entries,
    summarize,
)

ENTRIES = [
    {"final_answer": "Order 1 is late.", "total_duration_s": 1.0, "input_tokens": 100,
     "output_tokens": 20, "cost_usd": 0.001, "tool_calls": [{"ok": True}, {"ok": False}]},
    {"final_answer": MODEL_ERROR_MESSAGE, "model_error": "Timeout", "total_duration_s": 3.0,
     "input_tokens": 50, "output_tokens": 0, "cost_usd": 0.0005, "retry_count": 2},
    {"final_answer": "Fine.", "fallback": False, "total_duration_s": 2.0, "input_tokens": 10,
     "output_tokens": 10, "cost_usd": 0.0001, "tool_calls": [{"ok": True}]},
]


def test_read_entries_skips_malformed(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text('{"a": 1}\nnot json\n\n[1, 2]\n{"b": 2}\n', encoding="utf-8")
    assert read_entries(path) == ([{"a": 1}, {"b": 2}], 2)


def test_is_error() -> None:
    assert is_error({"model_error": "Timeout"})
    assert is_error({"error_class": "RateLimit"})
    assert not is_error({"final_answer": "ok"})


def test_is_fallback_prefers_logged_flag() -> None:
    assert is_fallback({"final_answer": MODEL_ERROR_MESSAGE})
    assert not is_fallback({"final_answer": MODEL_ERROR_MESSAGE, "fallback": False})
    assert is_fallback({"final_answer": "custom", "fallback": True})
    assert not is_fallback({"final_answer": "Order 1 is late."})


@pytest.mark.parametrize(
    ("values", "pct", "expected"),
    [([], 50, None), ([5.0], 95, 5.0), ([1, 2, 3, 4], 50, 2), ([1, 2, 3, 4], 95, 4)],
)
def test_percentile_nearest_rank(values, pct, expected) -> None:
    assert percentile(values, pct) == expected


def test_rate() -> None:
    assert rate(1, 4) == 0.25
    assert rate(0, 0) is None


def test_summarize() -> None:
    s = summarize(ENTRIES)
    assert s["questions"] == 3
    assert s["error_rate"] == pytest.approx(1 / 3)
    assert s["fallback_rate"] == pytest.approx(1 / 3)
    assert (s["retries_total"], s["questions_with_retries"], s["retries_max"]) == (2, 1, 2)
    assert s["tool_calls"] == 3
    assert s["tool_call_error_rate"] == pytest.approx(1 / 3)
    assert (s["latency_p50_s"], s["latency_p95_s"]) == (2.0, 3.0)
    assert s["tokens_total"] == 190
    assert s["cost_total_usd"] == pytest.approx(0.0016)


def test_summarize_unknown_cost_and_empty() -> None:
    assert summarize([{"cost_usd": None}])["cost_total_usd"] is None
    empty = summarize([])
    assert empty["questions"] == 0 and empty["error_rate"] is None


def test_formatters() -> None:
    assert fmt_pct(None) == "n/a" and fmt_pct(0.125) == "12.5%"
    assert fmt_num(None) == "n/a" and fmt_num(1.234) == "1.23" and fmt_num(7.6, 0) == "8"


def test_format_summary() -> None:
    text = format_summary(summarize(ENTRIES), skipped=1)
    assert "questions:            3" in text
    assert "error rate:           33.3%" in text
    assert "$0.001600 total" in text
    assert "malformed lines skipped: 1" in text
    assert "n/a (some prices missing)" in format_summary(summarize([{}]), 0)


def test_parse_args(tmp_path: Path) -> None:
    assert parse_args(["--path", str(tmp_path / "x")]).path == tmp_path / "x"


def test_main(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "none.jsonl"
    assert main(["--path", str(missing)]) == 1
    path = tmp_path / "log.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in ENTRIES), encoding="utf-8")
    assert main(["--path", str(path)]) == 0
    assert "questions:            3" in capsys.readouterr().out
