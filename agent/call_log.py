"""Append one JSON line per question to logs/agent_calls.jsonl (secrets redacted)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from agent.loop import QuestionOutcome

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "agent_calls.jsonl"
REDACTED = "[REDACTED]"


def redact(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def build_log_entry(outcome: QuestionOutcome, cost: dict, timestamp: datetime | None = None) -> dict:
    """Timestamp is wall-clock time of logging only; answers use the simulated date."""
    stamp = (timestamp or datetime.now(timezone.utc)).isoformat()
    return {
        "timestamp": stamp,
        "question": outcome.question,
        "as_of": outcome.as_of.isoformat(),
        "model": outcome.model,
        "tool_calls": outcome.tool_calls,
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
        "cost_usd": cost.get("cost_usd"),
        "cost_note": cost.get("note"),
        "total_duration_s": outcome.duration_s,
        "stop": outcome.stop,
        "model_error": outcome.model_error,
        "final_answer": outcome.answer,
    }


def append_log(entry: dict, secrets: Iterable[str], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = redact(json.dumps(entry, ensure_ascii=False, default=str), list(secrets))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
