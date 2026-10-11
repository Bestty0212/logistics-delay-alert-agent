"""Agent configuration from environment variables (.env)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_MAX_TOKENS_PER_CALL = 1024
DEFAULT_MAX_TOKENS_PER_QUESTION = 30000
DEFAULT_MODEL_TIMEOUT_SECONDS = 30.0
MAX_TOOL_CALLS = 5

API_KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}


class ConfigError(Exception):
    """Missing or invalid configuration; messages never contain secret values."""


@dataclass(frozen=True)
class AgentConfig:
    provider: str
    model: str
    max_tokens_per_call: int
    max_tokens_per_question: int
    model_timeout_seconds: float
    max_tool_calls: int = MAX_TOOL_CALLS


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set (add it to .env)")
    return value


def _positive_number(environ: Mapping[str, str], name: str, default: float, cast) -> float:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a positive number") from None
    if value <= 0:
        raise ConfigError(f"{name} must be a positive number")
    return value


def load_config(environ: Mapping[str, str]) -> AgentConfig:
    return AgentConfig(
        provider=_required(environ, "LLM_PROVIDER").lower(),
        model=_required(environ, "LLM_MODEL"),
        max_tokens_per_call=_positive_number(
            environ, "AGENT_MAX_TOKENS_PER_CALL", DEFAULT_MAX_TOKENS_PER_CALL, int
        ),
        max_tokens_per_question=_positive_number(
            environ, "AGENT_MAX_TOKENS_PER_QUESTION", DEFAULT_MAX_TOKENS_PER_QUESTION, int
        ),
        model_timeout_seconds=_positive_number(
            environ, "AGENT_MODEL_TIMEOUT_SECONDS", DEFAULT_MODEL_TIMEOUT_SECONDS, float
        ),
    )


def api_key_for(provider: str, environ: Mapping[str, str]) -> str:
    variable = API_KEY_VARIABLES.get(provider)
    if variable is None:
        raise ConfigError(f"unsupported LLM_PROVIDER: {provider}")
    return _required(environ, variable)


def secret_values(environ: Mapping[str, str]) -> list[str]:
    """Secret values that must never appear in logs or output."""
    return [environ[v] for v in API_KEY_VARIABLES.values() if environ.get(v)]
