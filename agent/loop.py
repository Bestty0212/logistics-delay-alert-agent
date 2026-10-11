"""The agent loop: question -> tool calls -> tool results -> final answer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

from agent.config import AgentConfig
from agent.prompt import build_system_prompt
from agent.provider import ModelError, ModelProvider
from agent.tool_bridge import ToolRunner, limit_reached, run_tool_call
from agent_tools.registry import TOOL_SPECS, call_tool

TOOL_LIMIT_MESSAGE = "I could not answer within the tool-call limit."
TOKEN_BUDGET_MESSAGE = "I could not answer within the token budget."
MODEL_ERROR_MESSAGE = "The model request failed or timed out."
NO_ANSWER_MESSAGE = "The model returned no answer."


@dataclass
class QuestionOutcome:
    question: str
    as_of: date
    model: str
    answer: str = ""
    stop: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0
    model_error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _finish(outcome: QuestionOutcome, answer: str, stop: str, started: float) -> QuestionOutcome:
    outcome.answer = answer
    outcome.stop = stop
    outcome.duration_s = round(time.perf_counter() - started, 3)
    return outcome


def answer_question(
    question: str,
    *,
    provider: ModelProvider,
    config: AgentConfig,
    as_of: date,
    runner: ToolRunner = call_tool,
    tools: list[dict] = TOOL_SPECS,
) -> QuestionOutcome:
    started = time.perf_counter()
    outcome = QuestionOutcome(question=question, as_of=as_of, model=provider.model_name)
    conversation = provider.start(build_system_prompt(as_of), tools, question)
    calls_used = 0
    allow_tools = True

    while True:
        try:
            turn = provider.next_turn(conversation, allow_tools=allow_tools)
        except ModelError as exc:
            outcome.model_error = str(exc)
            return _finish(outcome, MODEL_ERROR_MESSAGE, "model_error", started)
        outcome.input_tokens += turn.input_tokens
        outcome.output_tokens += turn.output_tokens

        if not allow_tools or not turn.tool_calls:
            text = turn.text.strip()
            if text:
                return _finish(outcome, text, "final_answer" if allow_tools else "tool_limit", started)
            fallback = NO_ANSWER_MESSAGE if allow_tools else TOOL_LIMIT_MESSAGE
            return _finish(outcome, fallback, "no_answer" if allow_tools else "tool_limit", started)

        if outcome.total_tokens > config.max_tokens_per_question:
            return _finish(outcome, TOKEN_BUDGET_MESSAGE, "token_budget", started)

        results = []
        for call in turn.tool_calls:
            if calls_used < config.max_tool_calls:
                result, record = run_tool_call(call, as_of, runner)
            else:
                result, record = limit_reached(call)
            calls_used += 1
            results.append(result)
            outcome.tool_calls.append(record)
        provider.add_tool_results(conversation, turn, results)

        if calls_used >= config.max_tool_calls:
            allow_tools = False
