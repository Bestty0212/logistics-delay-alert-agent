"""Run eval questions through the agent loop, check answers, and enforce the cost limit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date

from agent.config import AgentConfig
from agent.cost import estimate_cost
from agent.loop import QuestionOutcome, answer_question
from agent.provider import ModelProvider, ModelTurn, ToolCall, ToolResult
from agent.tool_bridge import ToolRunner
from agent_tools.registry import call_tool
from eval.checkers import Check, SpecError, all_passed, evaluate_answer

DRY_RUN_MODEL = "dry-run-scripted"


class ToolRecorder:
    """Wraps the tool runner and keeps every result, for the no-leak check."""

    def __init__(self, runner: ToolRunner = call_tool) -> None:
        self.runner = runner
        self.results: list[dict] = []

    def __call__(self, name: str, arguments: dict) -> dict:
        result = self.runner(name, arguments)
        self.results.append(result)
        return result


class ScriptedProvider:
    """Dry-run model: calls the question's scripted tools once, then gives its scripted answer."""

    model_name = DRY_RUN_MODEL

    def __init__(self, calls: list[list], answer: str) -> None:
        self.calls = calls
        self.answer = answer

    def start(self, system_prompt: str, tools: list[dict], question: str) -> dict:
        return {"turns": 0}

    def next_turn(self, conversation: dict, *, allow_tools: bool) -> ModelTurn:
        conversation["turns"] += 1
        if conversation["turns"] == 1 and self.calls and allow_tools:
            calls = [ToolCall(f"dry_{i}", n, a) for i, (n, a) in enumerate(self.calls)]
            return ModelTurn("", calls, 0, 0, "tool_use")
        return ModelTurn(self.answer, [], 0, 0, "end_turn")

    def add_tool_results(self, conversation: dict, turn: ModelTurn, results: list[ToolResult]) -> None:
        return None


def dry_run_provider(question: dict) -> ScriptedProvider:
    return ScriptedProvider(question["dry_run"]["calls"], question["dry_run"]["answer"])


class BudgetExceeded(Exception):
    """The cost limit was reached or the next question could exceed it."""


@dataclass
class BudgetGuard:
    """Tracks spend; with a limit, an unknown cost or reaching the limit stops the run."""

    limit_usd: float | None
    spent_usd: float = 0.0
    max_question_usd: float = 0.0

    def before_question(self) -> None:
        if self.limit_usd is None:
            return
        if self.spent_usd + self.max_question_usd > self.limit_usd:
            raise BudgetExceeded(
                f"spent ${self.spent_usd:.6f}; the next question could exceed the "
                f"${self.limit_usd:.2f} limit (largest question so far ${self.max_question_usd:.6f})"
            )

    def add(self, cost_usd: float | None) -> None:
        if cost_usd is None:
            if self.limit_usd is not None:
                raise BudgetExceeded("cost is unknown (prices missing), so the limit cannot be enforced")
            return
        self.spent_usd += cost_usd
        self.max_question_usd = max(self.max_question_usd, cost_usd)
        if self.limit_usd is not None and self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(f"spent ${self.spent_usd:.6f}, limit ${self.limit_usd:.2f}")


def checks_for(question: dict, gold_values: dict, outcome: QuestionOutcome,
               tool_results: list[dict]) -> list[Check]:
    try:
        return evaluate_answer(question, gold_values, outcome.answer, outcome.tool_calls,
                               tool_results)
    except SpecError as exc:
        return [Check("spec", False, str(exc))]


def result_record(question: dict, repeat: int, outcome: QuestionOutcome, checks: list[Check],
                  tool_results: list[dict], cost: dict, max_tool_calls: int) -> dict:
    return {
        "id": question["id"],
        "category": question["category"],
        "repeat": repeat,
        "question": question["question"],
        "as_of": question["as_of"],
        "model": outcome.model,
        "answer": outcome.answer,
        "stop": outcome.stop,
        "model_error": outcome.model_error,
        "tool_calls": outcome.tool_calls,
        "tool_results": tool_results,
        "checks": [asdict(c) for c in checks],
        "passed": all_passed(checks),
        "duration_s": outcome.duration_s,
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
        "total_tokens": outcome.total_tokens,
        "cost_usd": cost["cost_usd"],
        "hit_tool_limit": outcome.stop == "tool_limit" or len(outcome.tool_calls) >= max_tool_calls,
    }


def run_question(question: dict, gold_values: dict, *, provider: ModelProvider,
                 config: AgentConfig, pricing: dict, repeat: int = 1,
                 runner: ToolRunner = call_tool) -> tuple[dict, QuestionOutcome]:
    recorder = ToolRecorder(runner)
    outcome = answer_question(question["question"], provider=provider, config=config,
                              as_of=date.fromisoformat(question["as_of"]), runner=recorder)
    checks = checks_for(question, gold_values, outcome, recorder.results)
    cost = estimate_cost(pricing, outcome.model, outcome.input_tokens, outcome.output_tokens)
    record = result_record(question, repeat, outcome, checks, recorder.results, cost,
                           config.max_tool_calls)
    return record, outcome


@dataclass
class EvalRun:
    results: list[dict] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None
    spent_usd: float = 0.0


def run_eval(questions: list[dict], gold: dict, *,
             provider_for: Callable[[dict], ModelProvider], config: AgentConfig, pricing: dict,
             max_cost_usd: float | None, repeats: int = 1, runner: ToolRunner = call_tool,
             on_result: Callable[[dict, QuestionOutcome], None] | None = None) -> EvalRun:
    """Run every question `repeats` times; stop early when the cost limit is reached."""
    run = EvalRun()
    guard = BudgetGuard(max_cost_usd)
    try:
        for repeat in range(1, repeats + 1):
            for question in questions:
                guard.before_question()
                values = gold["entries"][question["id"]].get("values", {})
                record, outcome = run_question(question, values, provider=provider_for(question),
                                               config=config, pricing=pricing, repeat=repeat,
                                               runner=runner)
                run.results.append(record)
                if on_result:
                    on_result(record, outcome)
                guard.add(record["cost_usd"])
    except BudgetExceeded as exc:
        run.aborted, run.abort_reason = True, str(exc)
    run.spent_usd = guard.spent_usd
    return run
