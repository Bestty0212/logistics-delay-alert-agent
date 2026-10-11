#!/usr/bin/env python3
"""Ask the logistics agent a question (or start interactive mode with no question)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.call_log import append_log, build_log_entry  # noqa: E402
from agent.clock import SessionDateError, read_clock, resolve_session_as_of  # noqa: E402
from agent.config import AgentConfig, ConfigError, load_config, secret_values  # noqa: E402
from agent.cost import estimate_cost, load_pricing  # noqa: E402
from agent.factory import build_provider  # noqa: E402
from agent.loop import QuestionOutcome, answer_question  # noqa: E402
from agent.provider import ModelProvider  # noqa: E402
from etl.env import apply_env_file  # noqa: E402

EXIT_WORDS = {"exit", "quit"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", help="question; omit for interactive mode")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, help="YYYY-MM-DD; defaults to the simulated clock"
    )
    parser.add_argument("--verbose", action="store_true", help="show tool calls and durations")
    return parser.parse_args(argv)


def format_tool_calls(tool_calls: list[dict]) -> str:
    if not tool_calls:
        return "tool calls: none"
    lines = ["tool calls:"]
    for i, call in enumerate(tool_calls, 1):
        status = "ok" if call["ok"] else f"error {call['error_code']}"
        lines.append(
            f"  {i}. {call['name']}({json.dumps(call['arguments'], ensure_ascii=False)}) "
            f"-> {status}, {call['duration_ms']} ms"
        )
    return "\n".join(lines)


def format_usage(cost: dict) -> str:
    usage = f"tokens: {cost['input_tokens']} in / {cost['output_tokens']} out"
    if cost["cost_usd"] is None:
        return f"{usage} ({cost['note']})"
    return f"{usage}, cost ${cost['cost_usd']:.6f}"


def handle_question(
    question: str,
    *,
    provider: ModelProvider,
    config: AgentConfig,
    as_of: date,
    verbose: bool,
) -> QuestionOutcome:
    outcome = answer_question(question, provider=provider, config=config, as_of=as_of)
    cost = estimate_cost(load_pricing(), outcome.model, outcome.input_tokens, outcome.output_tokens)
    append_log(build_log_entry(outcome, cost), secret_values(os.environ))
    print(outcome.answer)
    if verbose:
        print(format_tool_calls(outcome.tool_calls))
        print(f"stop: {outcome.stop}, duration: {outcome.duration_s} s")
    print(format_usage(cost))
    return outcome


def interactive(**kwargs) -> None:
    print(f"Ask a question (as of {kwargs['as_of'].isoformat()}); type 'exit' to quit.")
    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            break
        if not question or question.lower() in EXIT_WORDS:
            break
        handle_question(question, **kwargs)


def main(argv: list[str] | None = None) -> int:
    apply_env_file(ROOT / ".env", os.environ)
    args = parse_args(argv)
    try:
        config = load_config(os.environ)
        provider = build_provider(config, os.environ)
        as_of = resolve_session_as_of(args.as_of, read_clock())
    except (ConfigError, SessionDateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    kwargs = {"provider": provider, "config": config, "as_of": as_of, "verbose": args.verbose}
    if args.question:
        handle_question(args.question, **kwargs)
    else:
        interactive(**kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
