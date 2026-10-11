"""Write raw transcripts only when they contain no secrets."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

SECRET_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "POSTGRES_PASSWORD",
    "AGENT_RO_PASSWORD",
)

SECRET_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"sk-ant-[A-Za-z0-9_\-]{8,}",
        r"\bsk-[A-Za-z0-9]{20,}",
        r"(?i)\b(api[_-]?key|password|secret)\b\s*[=:]\s*\S+",
    )
)


def secret_values(environ: Mapping[str, str]) -> list[str]:
    return [environ[v] for v in SECRET_VARIABLES if environ.get(v)]


def find_secrets(text: str, secrets: Iterable[str]) -> list[str]:
    """Reasons the text is unsafe; never includes the secret itself."""
    reasons = [f"value of a secret variable (#{i})" for i, s in enumerate(secrets) if s and s in text]
    reasons += [f"pattern {p.pattern}" for p in SECRET_PATTERNS if p.search(text)]
    return reasons


def transcript_record(result: dict) -> dict:
    keys = ("id", "category", "repeat", "question", "as_of", "model", "answer", "stop",
            "tool_calls", "tool_results", "input_tokens", "output_tokens", "duration_s",
            "cost_usd", "passed", "checks")
    return {k: result.get(k) for k in keys}


def write_transcript(path: Path, result: dict, secrets: Iterable[str]) -> list[str]:
    """Write the transcript and return [] or, if it contains a secret, skip it and return why."""
    text = json.dumps(transcript_record(result), indent=2, ensure_ascii=False, default=str)
    reasons = find_secrets(text, list(secrets))
    if reasons:
        return reasons
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return []
