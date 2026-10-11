"""DeepSeek adapter: OpenAI-compatible Chat Completions API with function calling."""

from __future__ import annotations

import json

import openai

from agent.model_errors import is_retryable_status, parse_retry_after
from agent.provider import ModelError, ModelTurn, ToolCall, ToolResult

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def to_openai_tools(tool_specs: list[dict]) -> list[dict]:
    """Registry specs already use JSON Schema `parameters`; wrap them as functions."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for spec in tool_specs
    ]


def parse_arguments(raw: object) -> object:
    """Decode the JSON argument string; malformed JSON is kept raw so validation rejects it."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return raw


def usage_tokens(usage: object) -> tuple[int, int]:
    """(input, output) tokens; OpenAI-style usage names them prompt and completion tokens."""
    if usage is None:
        return 0, 0
    input_tokens = getattr(usage, "input_tokens", None)
    if input_tokens is None:
        input_tokens = getattr(usage, "prompt_tokens", 0)
    output_tokens = getattr(usage, "output_tokens", None)
    if output_tokens is None:
        output_tokens = getattr(usage, "completion_tokens", 0)
    return int(input_tokens or 0), int(output_tokens or 0)


def first_message(response: object) -> tuple[object, str]:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ModelError("EmptyResponse", error_class="EmptyResponse", retryable=False)
    return choices[0].message, choices[0].finish_reason or ""


def parse_response(response: object) -> ModelTurn:
    message, finish_reason = first_message(response)
    calls = [
        ToolCall(id=c.id, name=c.function.name, arguments=parse_arguments(c.function.arguments))
        for c in (message.tool_calls or [])
    ]
    input_tokens, output_tokens = usage_tokens(getattr(response, "usage", None))
    return ModelTurn(
        text=message.content or "",
        tool_calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=finish_reason,
    )


def assistant_message(response: object) -> dict:
    """The assistant turn as sent back to the API, with the raw argument strings."""
    message, _ = first_message(response)
    entry: dict = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        entry["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.function.name, "arguments": c.function.arguments or ""},
            }
            for c in message.tool_calls
        ]
    return entry


def tool_result_message(result: ToolResult) -> dict:
    """Errors stay visible to the model through the result's own ok/error fields."""
    return {
        "role": "tool",
        "tool_call_id": result.call_id,
        "content": json.dumps(result.content, ensure_ascii=False),
    }


def to_model_error(exc: Exception) -> ModelError:
    """Map an SDK exception to ModelError; messages carry the class and status, never details."""
    name = type(exc).__name__
    if isinstance(exc, openai.APIConnectionError):  # includes APITimeoutError
        return ModelError(name, error_class=name, retryable=True)
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        headers = getattr(exc.response, "headers", None)
        return ModelError(
            f"{name} (status {status})",
            error_class=name,
            retryable=is_retryable_status(status),
            retry_after_s=parse_retry_after(headers),
        )
    return ModelError(name, error_class=name, retryable=False)


class DeepSeekProvider:
    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens: int,
        timeout_seconds: float,
        client: object | None = None,
        base_url: str = DEEPSEEK_BASE_URL,
    ) -> None:
        self.model_name = model
        self._max_tokens = max_tokens
        self._client = client or openai.OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=0
        )

    def start(self, system_prompt: str, tools: list[dict], question: str) -> dict:
        return {
            "tools": to_openai_tools(tools),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        }

    def request_arguments(self, conversation: dict, allow_tools: bool) -> dict:
        arguments = {
            "model": self.model_name,
            "max_tokens": self._max_tokens,
            "messages": conversation["messages"],
        }
        if conversation["tools"]:
            arguments["tools"] = conversation["tools"]
            arguments["tool_choice"] = "auto" if allow_tools else "none"
        return arguments

    def next_turn(self, conversation: dict, *, allow_tools: bool) -> ModelTurn:
        try:
            response = self._client.chat.completions.create(
                **self.request_arguments(conversation, allow_tools)
            )
        except openai.OpenAIError as exc:
            raise to_model_error(exc) from None
        turn = parse_response(response)
        conversation["messages"].append(assistant_message(response))
        return turn

    def add_tool_results(
        self, conversation: dict, turn: ModelTurn, results: list[ToolResult]
    ) -> None:
        conversation["messages"].extend(tool_result_message(r) for r in results)
