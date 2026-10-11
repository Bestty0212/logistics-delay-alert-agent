"""Provider-neutral interface between the agent loop and a language model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: object  # raw from the model; may be malformed


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: dict
    is_error: bool


@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    stop_reason: str


class ModelError(Exception):
    """The model request failed or timed out; message never contains secrets.

    error_class names the failure (e.g. "RateLimitError"); retryable marks transient
    failures; retry_after_s is the server's retry hint in seconds, when it sent one.
    """

    def __init__(
        self,
        message: str,
        *,
        error_class: str | None = None,
        retryable: bool = False,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class or message
        self.retryable = retryable
        self.retry_after_s = retry_after_s


class ModelProvider(Protocol):
    model_name: str

    def start(self, system_prompt: str, tools: list[dict], question: str) -> object:
        """Return an opaque conversation owned by the provider."""

    def next_turn(self, conversation: object, *, allow_tools: bool) -> ModelTurn:
        """Ask the model for its next turn; allow_tools=False forces a text answer."""

    def add_tool_results(
        self, conversation: object, turn: ModelTurn, results: list[ToolResult]
    ) -> None:
        """Append one result per tool call of `turn` to the conversation."""
