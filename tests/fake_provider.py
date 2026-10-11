"""Scripted fake model for offline agent-loop tests (never calls the network)."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.provider import ModelError, ModelTurn, ToolCall, ToolResult


def tool_turn(*calls: tuple[str, object], tokens: tuple[int, int] = (10, 5)) -> ModelTurn:
    return ModelTurn(
        text="",
        tool_calls=[ToolCall(id=f"call_{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)],
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        stop_reason="tool_use",
    )


def text_turn(text: str, tokens: tuple[int, int] = (10, 5)) -> ModelTurn:
    return ModelTurn(text=text, tool_calls=[], input_tokens=tokens[0],
                     output_tokens=tokens[1], stop_reason="end_turn")


@dataclass
class FakeProvider:
    script: list[ModelTurn | Exception]
    model_name: str = "fake-model"
    allow_tools_seen: list[bool] = field(default_factory=list)
    results_seen: list[list[ToolResult]] = field(default_factory=list)
    system_prompt: str = ""
    question: str = ""

    def start(self, system_prompt: str, tools: list[dict], question: str) -> dict:
        self.system_prompt = system_prompt
        self.question = question
        return {"turns": 0}

    def next_turn(self, conversation: dict, *, allow_tools: bool) -> ModelTurn:
        self.allow_tools_seen.append(allow_tools)
        step = self.script[min(conversation["turns"], len(self.script) - 1)]
        conversation["turns"] += 1
        if isinstance(step, Exception):
            raise step
        return step

    def add_tool_results(self, conversation: dict, turn: ModelTurn, results: list[ToolResult]) -> None:
        assert [r.call_id for r in results] == [c.id for c in turn.tool_calls]
        self.results_seen.append(results)


class RecordingRunner:
    """Stands in for registry.call_tool; records calls and returns scripted results."""

    def __init__(self, result: dict | None = None, raises: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.result = result or {"ok": True, "as_of": "2016-06-30", "data": {"x": 1}}
        self.raises = raises

    def __call__(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        if self.raises:
            raise self.raises
        return self.result


__all__ = ["FakeProvider", "RecordingRunner", "ModelError", "text_turn", "tool_turn"]
