"""Anthropic Messages API adapter with tool use."""

from __future__ import annotations

import json

import anthropic

from agent.provider import ModelError, ModelTurn, ToolCall, ToolResult


def to_anthropic_tools(tool_specs: list[dict]) -> list[dict]:
    """Registry specs use `parameters`; the Messages API expects `input_schema`."""
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "input_schema": spec["parameters"],
        }
        for spec in tool_specs
    ]


def parse_response(response) -> ModelTurn:
    text = "".join(b.text for b in response.content if b.type == "text")
    calls = [
        ToolCall(id=b.id, name=b.name, arguments=b.input)
        for b in response.content
        if b.type == "tool_use"
    ]
    return ModelTurn(
        text=text,
        tool_calls=calls,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        stop_reason=response.stop_reason or "",
    )


def tool_result_block(result: ToolResult) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": result.call_id,
        "content": json.dumps(result.content, ensure_ascii=False),
        "is_error": result.is_error,
    }


class AnthropicProvider:
    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens: int,
        timeout_seconds: float,
        client: object | None = None,
    ) -> None:
        self.model_name = model
        self._max_tokens = max_tokens
        self._client = client or anthropic.Anthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )

    def start(self, system_prompt: str, tools: list[dict], question: str) -> dict:
        return {
            "system": system_prompt,
            "tools": to_anthropic_tools(tools),
            "messages": [{"role": "user", "content": question}],
        }

    def next_turn(self, conversation: dict, *, allow_tools: bool) -> ModelTurn:
        try:
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=self._max_tokens,
                system=conversation["system"],
                tools=conversation["tools"],
                tool_choice={"type": "auto" if allow_tools else "none"},
                messages=conversation["messages"],
            )
        except anthropic.APIStatusError as exc:
            raise ModelError(f"{type(exc).__name__} (status {exc.status_code})") from None
        except anthropic.APIError as exc:
            raise ModelError(type(exc).__name__) from None
        # Content blocks (including any thinking blocks) go back unchanged.
        conversation["messages"].append({"role": "assistant", "content": response.content})
        return parse_response(response)

    def add_tool_results(
        self, conversation: dict, turn: ModelTurn, results: list[ToolResult]
    ) -> None:
        conversation["messages"].append(
            {"role": "user", "content": [tool_result_block(r) for r in results]}
        )
