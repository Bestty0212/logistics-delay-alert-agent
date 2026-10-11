"""Offline tests for eval metrics, runner, budget, transcripts, reports and gold helpers."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from agent.config import AgentConfig
from eval.checkers import Check
from eval.gold import (
    GoldError,
    gold_params,
    gold_problems,
    load_gold,
    load_questions,
    to_jsonable,
    validate_question,
)
from eval.metrics import (
    accuracy,
    accuracy_by_category,
    average,
    average_cost,
    check_pass_rates,
    percentile,
    ratio,
    stability,
    summarize,
    tool_call_success_rate,
)
from eval.report import (
    build_failures_report,
    build_summary_report,
    num,
    pct,
    table,
    tool_call_lines,
    usd,
)
from eval.runner import (
    DRY_RUN_MODEL,
    BudgetExceeded,
    BudgetGuard,
    ScriptedProvider,
    ToolRecorder,
    checks_for,
    dry_run_provider,
    run_eval,
    run_question,
)
from eval.transcripts import find_secrets, secret_values, transcript_record, write_transcript
from scripts.run_eval import (
    SetupError,
    check_dates,
    live_setup,
    parse_args,
    report_paths,
    select_questions,
)
from tests.fake_provider import FakeProvider, RecordingRunner, text_turn, tool_turn

CONFIG = AgentConfig("anthropic", "m", 256, 10_000, 5.0)
PRICING = {"models": {"m": {"input_per_million": 1.0, "output_per_million": 0.0}}}
QUESTIONS = load_questions()
FAKE_KEY = "sk-ant-test-0123456789-SECRET"


def result(qid="Q", category="lookup", passed=True, duration=1.0, tokens=10, cost=0.01,
           calls=(), repeat=1, answer="a", checks=None, limit=False):
    return {
        "id": qid, "category": category, "passed": passed, "duration_s": duration,
        "total_tokens": tokens, "cost_usd": cost, "tool_calls": list(calls), "repeat": repeat,
        "answer": answer, "hit_tool_limit": limit, "stop": "final_answer",
        "question": "q?", "as_of": "2016-06-30",
        "checks": checks if checks is not None else [{"name": "required", "passed": passed,
                                                      "detail": "" if passed else "missing x"}],
    }


def simple_question(qid="Q1", answer_pattern="open"):
    return {"id": qid, "category": "lookup", "question": "Is order 1 open?", "as_of": "2016-06-30",
            "gold": {"query": None}, "checks": {"required": [answer_pattern], "tool": None},
            "dry_run": {"calls": [], "answer": "open"}}


# --- metrics --------------------------------------------------------------------


def test_basic_metric_helpers_with_empty_and_zero() -> None:
    assert ratio(1, 0) is None and ratio(0, 4) == 0.0
    assert average([]) is None and average([1.0, 3.0]) == 2.0
    assert percentile([], 95) is None
    assert percentile([5.0], 95) == 5.0
    assert percentile([float(i) for i in range(1, 21)], 95) == 19.0
    assert percentile([float(i) for i in range(1, 101)], 95) == 95.0


def test_accuracy_and_categories() -> None:
    results = [result(passed=True), result(passed=False), result(category="trap", passed=True)]
    assert accuracy(results) == pytest.approx(2 / 3)
    assert accuracy([]) is None
    table_ = accuracy_by_category(results)
    assert table_["lookup"] == {"passed": 1, "total": 2, "accuracy": 0.5}
    assert table_["aggregate"] == {"passed": 0, "total": 0, "accuracy": None}


def test_tool_call_success_rate_and_zero_calls() -> None:
    calls = [{"ok": True}, {"ok": False}, {"ok": True}, {"ok": True}]
    assert tool_call_success_rate([result(calls=calls)]) == 0.75
    assert tool_call_success_rate([result()]) is None
    assert tool_call_success_rate([]) is None


def test_average_cost_unknown_when_any_missing() -> None:
    assert average_cost([result(cost=0.02), result(cost=0.04)]) == pytest.approx(0.03)
    assert average_cost([result(cost=0.02), result(cost=None)]) is None
    assert average_cost([]) is None


def test_check_pass_rates_and_stability() -> None:
    a = result(qid="A", passed=True, answer="x", repeat=1)
    b = result(qid="A", passed=False, answer="y", repeat=2)
    c = result(qid="B", passed=True, answer="z", repeat=1)
    d = result(qid="B", passed=True, answer="z", repeat=2)
    assert check_pass_rates([a, b]) == {"required": 0.5}
    assert check_pass_rates([]) == {}
    s = stability([a, b, c, d])
    assert s["A"] == {"runs": 2, "passes": 1, "outcome_changed": True, "answer_changed": True}
    assert s["B"]["outcome_changed"] is False and s["B"]["answer_changed"] is False


def test_summarize_empty_and_full() -> None:
    empty = summarize([])
    assert empty["accuracy"] is None and empty["latency_p95_s"] is None
    assert empty["cost_total_usd"] is None and empty["tool_limit_hits"] == 0
    full = summarize([result(duration=1.0, limit=True), result(category="trap", duration=3.0)])
    assert full["accuracy"] == 1.0 and full["trap_pass_rate"] == 1.0
    assert full["latency_avg_s"] == 2.0 and full["latency_p95_s"] == 3.0
    assert full["cost_total_usd"] == pytest.approx(0.02)
    assert full["tool_limit_hits"] == 1


# --- budget ---------------------------------------------------------------------


def test_budget_guard() -> None:
    guard = BudgetGuard(None)
    guard.add(None)
    guard.add(5.0)
    guard.before_question()
    limited = BudgetGuard(0.10)
    limited.before_question()
    limited.add(0.04)
    limited.before_question()
    limited.add(0.04)
    with pytest.raises(BudgetExceeded, match="next question could exceed"):
        limited.before_question()
    with pytest.raises(BudgetExceeded, match="spent"):
        limited.add(0.03)
    with pytest.raises(BudgetExceeded, match="unknown"):
        BudgetGuard(1.0).add(None)


def test_max_cost_aborts_run() -> None:
    """Each answer costs 0.4 USD at these fake prices; a 1.0 limit stops after two."""
    questions = [simple_question(f"Q{i}") for i in range(5)]
    gold = {"entries": {q["id"]: {"values": {}} for q in questions}}
    providers = []

    def provider_for(_q):
        providers.append(FakeProvider([text_turn("open", tokens=(400_000, 0))], model_name="m"))
        return providers[-1]

    run = run_eval(questions, gold, provider_for=provider_for, config=CONFIG, pricing=PRICING,
                   max_cost_usd=1.0, runner=RecordingRunner())
    assert run.aborted and "could exceed" in run.abort_reason
    assert len(run.results) == 2 and len(providers) == 2
    assert run.spent_usd == pytest.approx(0.8)


def test_run_without_limit_completes_with_repeats() -> None:
    questions = [simple_question("Q1"), simple_question("Q2")]
    gold = {"entries": {q["id"]: {"values": {}} for q in questions}}
    run = run_eval(questions, gold, provider_for=dry_run_provider, config=CONFIG, pricing={},
                   max_cost_usd=None, repeats=3, runner=RecordingRunner())
    assert not run.aborted
    assert [(r["id"], r["repeat"]) for r in run.results][:3] == [("Q1", 1), ("Q2", 1), ("Q1", 2)]
    assert len(run.results) == 6 and all(r["passed"] for r in run.results)


# --- runner pieces ----------------------------------------------------------------


def test_tool_recorder_keeps_results() -> None:
    inner = RecordingRunner(result={"ok": True, "data": {"a": 1}})
    recorder = ToolRecorder(inner)
    assert recorder("get_order_timeline", {"order_id": 1}) == {"ok": True, "data": {"a": 1}}
    assert recorder.results == [{"ok": True, "data": {"a": 1}}]
    assert inner.calls == [("get_order_timeline", {"order_id": 1})]


def test_scripted_provider_calls_tools_once_then_answers() -> None:
    provider = ScriptedProvider([["get_order_timeline", {"order_id": 1}]], "done")
    conversation = provider.start("s", [], "q")
    first = provider.next_turn(conversation, allow_tools=True)
    assert [c.name for c in first.tool_calls] == ["get_order_timeline"]
    assert provider.next_turn(conversation, allow_tools=True).text == "done"
    assert provider.add_tool_results(conversation, first, []) is None
    no_tools = ScriptedProvider([], "answer")
    assert no_tools.next_turn(no_tools.start("s", [], "q"), allow_tools=True).text == "answer"
    assert dry_run_provider(QUESTIONS[0]).model_name == DRY_RUN_MODEL


def test_run_question_records_leak_from_tool_result() -> None:
    """A planted forbidden field in a tool result fails the no-leak check."""
    question = {**simple_question(), "checks": {"tool": None}}
    planted = RecordingRunner(result={"ok": True, "data": {"delivery_status": "Late delivery"}})
    provider = FakeProvider([tool_turn(("get_order_timeline", {"order_id": 1})),
                             text_turn("Order 1 is open.")])
    record, _ = run_question(question, {}, provider=provider, config=CONFIG, pricing={},
                             runner=planted)
    assert not record["passed"]
    leak = next(c for c in record["checks"] if c["name"] == "no_leak")
    assert not leak["passed"] and "delivery_status in tool results" in leak["detail"]
    assert record["cost_usd"] is None and record["tool_results"][0]["data"]


def test_run_question_flags_tool_limit() -> None:
    provider = FakeProvider([tool_turn(("list_at_risk_orders", {}))] * 5 + [text_turn("open")])
    record, _ = run_question(simple_question(), {}, provider=provider, config=CONFIG,
                             pricing=PRICING, runner=RecordingRunner())
    assert record["hit_tool_limit"] is True and record["stop"] == "tool_limit"


def test_checks_for_turns_spec_error_into_failed_check() -> None:
    question = {**simple_question(), "checks": {"numbers": [{"value": "x", "kind": "count"}]}}
    outcome = type("O", (), {"answer": "1", "tool_calls": []})()
    checks = checks_for(question, {}, outcome, [])
    assert checks == [Check("spec", False, "gold value 'x' is missing")]


# --- transcripts ------------------------------------------------------------------


def test_find_secrets_never_returns_the_value() -> None:
    reasons = find_secrets(f"key {FAKE_KEY}", [FAKE_KEY])
    assert reasons and all(FAKE_KEY not in r for r in reasons)
    assert find_secrets("password = hunter2", []) != []
    assert find_secrets("Order 1 is open.", [FAKE_KEY, ""]) == []


def test_write_transcript_skips_secrets(tmp_path) -> None:
    clean = result(answer="Order 1 is open.")
    assert write_transcript(tmp_path / "ok.json", clean, [FAKE_KEY]) == []
    assert json.loads((tmp_path / "ok.json").read_text())["answer"] == "Order 1 is open."
    dirty = result(answer=f"my key is {FAKE_KEY}")
    assert write_transcript(tmp_path / "bad.json", dirty, [FAKE_KEY])
    assert not (tmp_path / "bad.json").exists()


def test_secret_values_and_record_keys() -> None:
    env = {"ANTHROPIC_API_KEY": "k", "POSTGRES_PASSWORD": "p", "AGENT_RO_PASSWORD": "",
           "OTHER": "x"}
    assert secret_values(env) == ["k", "p"]
    assert set(transcript_record(result())) >= {"id", "answer", "tool_calls", "tool_results"}


# --- reports --------------------------------------------------------------------

META = {"run_date": "2026-10-10", "mode": "live", "model": "m", "repeats": 2,
        "clock_date": "2016-08-31", "max_cost_usd": 0.25, "aborted": True,
        "abort_reason": "spent $0.25", "transcript_notes": ["T1_r1.json: pattern"]}


def test_formatters_and_table() -> None:
    assert pct(None) == "n/a" and pct(0.5) == "50.0%"
    assert num(None) == "n/a" and num(1.234) == "1.23"
    assert usd(None) == "n/a" and usd(0.25) == "$0.250000"
    assert table(["a"], [["1"]]) == ["| a |", "|---|", "| 1 |"]
    assert tool_call_lines([]) == ["- (no tool calls)"]


def test_summary_report_contains_tables_and_notes() -> None:
    results = [result(qid="A", repeat=1), result(qid="A", repeat=2, passed=False, answer="b")]
    text = build_summary_report(summarize(results), results, META)
    for phrase in ("Answer accuracy", "Trap pass rate", "Tool-call success rate",
                   "95th-percentile latency", "Average cost per question", "5-call limit",
                   "Accuracy by category", "Stability across repeats", "Run aborted",
                   "Transcript not written"):
        assert phrase in text
    assert build_summary_report(summarize([]), [], {**META, "repeats": 1, "aborted": False})


def test_failures_report_lists_only_failures() -> None:
    calls = [{"name": "get_order_timeline", "arguments": {"order_id": 1}, "ok": False,
              "error_code": "ORDER_NOT_FOUND"}]
    results = [result(qid="OK"), result(qid="BAD", passed=False, answer="wrong", calls=calls)]
    gold = {"entries": {"BAD": {"values": {"n": 3}, "sql": "SELECT 1", "params": {}},
                        "OK": {"values": {}}}}
    text = build_failures_report(results, gold, META)
    assert "## BAD" in text and "## OK" not in text
    assert "SELECT 1" in text and "wrong" in text and "ORDER_NOT_FOUND" in text
    assert '"n": 3' in text and "missing x" in text
    assert "0 failed of 0 runs" in build_failures_report([], gold, META)


# --- gold helpers and question file -------------------------------------------------


def test_question_file_shape() -> None:
    counts = {}
    for q in QUESTIONS:
        counts[q["category"]] = counts.get(q["category"], 0) + 1
    assert counts == {"lookup": 6, "aggregate": 8, "reasoning": 4, "trap": 12}
    assert len({q["question"] for q in QUESTIONS}) == 30


def test_committed_gold_covers_every_question() -> None:
    gold = load_gold()
    assert gold_problems(QUESTIONS, gold, date.fromisoformat(gold["clock_date"])) == []
    for qid, entry in gold["entries"].items():
        if entry["query"]:
            assert entry["sql"] and entry["row_count"] == 1, qid


def test_gold_problems_detects_staleness() -> None:
    gold = {"clock_date": "2016-08-31", "entries": {
        "L1": {"question": "changed", "as_of": "2016-06-30"}}}
    problems = gold_problems(QUESTIONS[:2], gold, date(2016, 7, 31))
    assert any("clock" in p for p in problems)
    assert any(p.startswith("L1:") for p in problems)
    assert any(p.startswith("L2: no gold entry") for p in problems)


def test_validate_question_and_helpers(tmp_path) -> None:
    with pytest.raises(GoldError, match="missing keys"):
        validate_question({"id": "X"})
    with pytest.raises(GoldError, match="unknown category"):
        validate_question({**simple_question(), "category": "other"})
    with pytest.raises(GoldError, match="unknown gold query"):
        validate_question({**simple_question(), "gold": {"query": "nope"}})
    assert to_jsonable(date(2016, 1, 2)) == "2016-01-02"
    assert to_jsonable(Decimal("0.5")) == 0.5 and to_jsonable(3) == 3
    params = gold_params({"as_of": "2016-06-30",
                          "gold": {"query": "order_exists", "params": {"order_id": 1}}})
    assert params == {"order_id": 1}
    params = gold_params({"as_of": "2016-06-30",
                          "gold": {"query": "order_status", "params": {"order_id": 1}}})
    assert params["as_of"] == date(2016, 6, 30)
    with pytest.raises(GoldError, match="not found"):
        load_gold(tmp_path / "absent.json")
    dup = tmp_path / "q.jsonl"
    dup.write_text("\n".join(json.dumps(simple_question("D")) for _ in range(2)))
    with pytest.raises(GoldError, match="duplicate"):
        load_questions(dup)


# --- run_eval.py helpers --------------------------------------------------------------


def test_parse_args_and_select() -> None:
    args = parse_args(["--dry-run", "--repeats", "2", "--max-cost-usd", "0.25", "--ids", "L1,T1"])
    assert args.dry_run and args.repeats == 2 and args.max_cost_usd == 0.25
    with pytest.raises(SystemExit):
        parse_args(["--repeats", "0"])
    with pytest.raises(SystemExit):
        parse_args(["--max-cost-usd", "-1"])
    assert [q["id"] for q in select_questions(QUESTIONS, "T1, L1")] == ["L1", "T1"]
    assert select_questions(QUESTIONS, None) is QUESTIONS
    with pytest.raises(SetupError, match="ZZ"):
        select_questions(QUESTIONS, "L1,ZZ")


def test_check_dates_against_clock() -> None:
    check_dates(QUESTIONS, date(2016, 8, 31))
    with pytest.raises(SetupError, match="replay not started"):
        check_dates(QUESTIONS, None)
    with pytest.raises(SetupError, match="later than the clock"):
        check_dates(QUESTIONS, date(2016, 6, 30))


def test_live_setup_requires_limit_and_prices(monkeypatch) -> None:
    env = {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-haiku-5-5"}
    with pytest.raises(SetupError, match="--max-cost-usd"):
        live_setup(parse_args([]), env)
    monkeypatch.setattr("scripts.run_eval.load_pricing", lambda: {})
    with pytest.raises(SetupError, match="prices"):
        live_setup(parse_args(["--max-cost-usd", "0.25"]), env)
    monkeypatch.setattr("scripts.run_eval.load_pricing", lambda: {"models": {
        "claude-haiku-5-5": {"input_per_million": 1.0, "output_per_million": 5.0}}})
    config, pricing = live_setup(parse_args(["--max-cost-usd", "0.25"]), env)
    assert config.model == "claude-haiku-5-5" and pricing["models"]


def test_report_paths() -> None:
    summary, failures, transcripts = report_paths("2026-10-10", dry_run=True)
    assert summary.name == "agent_eval_dryrun_2026-10-10.md"
    assert failures.name == "agent_eval_failures_dryrun_2026-10-10.md"
    assert transcripts.name == "dryrun_2026-10-10"
    assert report_paths("2026-10-10", dry_run=False)[0].name == "agent_eval_2026-10-10.md"
