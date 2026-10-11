"""Build the configured model provider."""

from __future__ import annotations

from collections.abc import Mapping

from agent.config import AgentConfig, ConfigError, api_key_for
from agent.provider import ModelProvider


def build_provider(config: AgentConfig, environ: Mapping[str, str]) -> ModelProvider:
    if config.provider == "anthropic":
        from agent.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            model=config.model,
            api_key=api_key_for("anthropic", environ),
            max_tokens=config.max_tokens_per_call,
            timeout_seconds=config.model_timeout_seconds,
        )
    if config.provider == "deepseek":
        from agent.deepseek_provider import DeepSeekProvider

        return DeepSeekProvider(
            model=config.model,
            api_key=api_key_for("deepseek", environ),
            max_tokens=config.max_tokens_per_call,
            timeout_seconds=config.model_timeout_seconds,
        )
    raise ConfigError(f"unsupported LLM_PROVIDER: {config.provider}")
