"""Offline tests for the DeepSeek adapter and model-error helpers (fake client; no network)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx2
import openai
import pytest

from agent.config import AgentConfig, ConfigError, api_key_for, secret_values
from agent.deepseek_provider import (
    DEEPSEEK_BASE_URL,
    DeepSeekProvider,
    assistant_message,
    parse_arguments,
    parse_response,
    to_model_error,
    to_openai_tools,
    tool_result_message,
    usage_tokens,
)
from agent.factory import build_provider
from agent.loop import MODEL_ERROR_MESSAGE, answer_question
from agent.model_errors import is_retryable_status, parse_retry_after
from agent.provider import ModelError, ToolCall, ToolResult
from agent_tools.registry import TOOL_SPECS
from tests.fake_provider import RecordingRunner

FAKE_KEY = "sk-test-deepseek-0123456789abcdef"
URL = "https://api.deepseek.com/chat/completions"
CONFIG = AgentConfig("deepseek", "deepseek-chat", 256, 10_000, 5.0)


# --- fakes ----------------------------------------------------------------------


def tool_call(call_id: str, name: str, arguments: str):
    return SimpleNamespace(id=call_id, type="function",
                           function=SimpleNamespace(name=name, arguments=arguments))


def response(content=None, calls=None, finish="stop", usage=(12, 7)):
    message = SimpleNamespace(role="assistant", content=content, tool_calls=calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1],
                              total_tokens=sum(usage)),
    )


class FakeCompletions:
    def __init__(self, *steps) -> None:
        self.steps = list(steps)
        self.kwargs: list[dict] = []

    def create(self, **kwargs):
        self.kwargs.append(json.loads(json.dumps(kwargs, default=str)))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def provider_with(*steps) -> tuple[DeepSeekProvider, FakeCompletions]:
    completions = FakeCompletions(*steps)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return DeepSeekProvider("deepseek-chat", FAKE_KEY, 256, 5.0, client=client), completions


def status_error(cls, status: int, headers: dict | None = None):
    request = httpx2.Request("POST", URL)
    reply = httpx2.Response(status, headers=headers or {}, request=request)
    return cls("error body", response=reply, body=None)


# --- request and response shapes ---------------------------------------------------


def test_to_openai_tools_wraps_every_spec() -> None:
    tools = to_openai_tools(TOOL_SPECS)
    assert [t["function"]["name"] for t in tools] == [s["name"] for s in TOOL_SPECS]
    assert all(t["type"] == "function" for t in tools)
    assert tools[0]["function"]["parameters"] == TOOL_SPECS[0]["parameters"]


def test_parse_arguments() -> None:
    assert parse_arguments('{"order_id": 5}') == {"order_id": 5}
    assert parse_arguments("") == {}
    assert parse_arguments("   ") == {}
    assert parse_arguments('{"order_id": 5') == '{"order_id": 5'  # malformed kept raw
    assert parse_arguments({"a": 1}) == {"a": 1}
    assert parse_arguments(None) is None


def test_usage_tokens_handles_both_namings_and_missing() -> None:
    assert usage_tokens(SimpleNamespace(prompt_tokens=10, completion_tokens=3)) == (10, 3)
    assert usage_tokens(SimpleNamespace(input_tokens=4, output_tokens=2)) == (4, 2)
    assert usage_tokens(SimpleNamespace(prompt_tokens=None, completion_tokens=None)) == (0, 0)
    assert usage_tokens(None) == (0, 0)


def test_parse_response_text_and_tool_calls() -> None:
    turn = parse_response(response("Hello", finish="stop"))
    assert (turn.text, turn.tool_calls, turn.stop_reason) == ("Hello", [], "stop")
    assert (turn.input_tokens, turn.output_tokens) == (12, 7)
    calls = [tool_call("c1", "get_order_timeline", '{"order_id": 37065}'),
             tool_call("c2", "list_at_risk_orders", "{bad json")]
    turn = parse_response(response(None, calls, finish="tool_calls"))
    assert turn.text == ""
    assert turn.tool_calls == [ToolCall("c1", "get_order_timeline", {"order_id": 37065}),
                               ToolCall("c2", "list_at_risk_orders", "{bad json")]
    assert turn.stop_reason == "tool_calls"


def test_empty_choices_is_a_non_retryable_model_error() -> None:
    with pytest.raises(ModelError) as info:
        parse_response(SimpleNamespace(choices=[], usage=None))
    assert info.value.error_class == "EmptyResponse" and info.value.retryable is False


def test_assistant_and_tool_messages() -> None:
    calls = [tool_call("c1", "get_order_timeline", '{"order_id": 1}')]
    entry = assistant_message(response(None, calls, finish="tool_calls"))
    assert entry == {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "get_order_timeline", "arguments": '{"order_id": 1}'}}]}
    assert assistant_message(response("Hi")) == {"role": "assistant", "content": "Hi"}
    message = tool_result_message(ToolResult("c1", {"ok": False, "error": {"code": "X"}}, True))
    assert message["role"] == "tool" and message["tool_call_id"] == "c1"
    assert json.loads(message["content"]) == {"ok": False, "error": {"code": "X"}}


# --- the adapter end to end with a fake client --------------------------------------


def test_request_shape_and_conversation_flow() -> None:
    calls = [tool_call("c1", "get_order_timeline", '{"order_id": 37065}')]
    provider, completions = provider_with(response(None, calls, finish="tool_calls"),
                                          response("Order 37065 is overdue."))
    conversation = provider.start("system text", TOOL_SPECS, "Where is 37065?")
    first = provider.next_turn(conversation, allow_tools=True)
    sent = completions.kwargs[0]
    assert sent["model"] == "deepseek-chat" and sent["max_tokens"] == 256
    assert sent["tool_choice"] == "auto"
    assert sent["messages"][:2] == [{"role": "system", "content": "system text"},
                                    {"role": "user", "content": "Where is 37065?"}]
    provider.add_tool_results(conversation, first, [ToolResult("c1", {"ok": True}, False)])
    assert conversation["messages"][-1]["role"] == "tool"
    final = provider.next_turn(conversation, allow_tools=False)
    assert completions.kwargs[1]["tool_choice"] == "none"
    assert final.text == "Order 37065 is overdue."
    assert [m["role"] for m in conversation["messages"]] == [
        "system", "user", "assistant", "tool", "assistant"]


def test_no_tools_means_no_tool_choice() -> None:
    provider, completions = provider_with(response("hi"))
    provider.next_turn(provider.start("s", [], "q"), allow_tools=True)
    assert "tools" not in completions.kwargs[0] and "tool_choice" not in completions.kwargs[0]


def test_works_inside_agent_loop() -> None:
    calls = [tool_call("c1", "get_order_timeline", '{"order_id": 37065}')]
    provider, _ = provider_with(response(None, calls, finish="tool_calls", usage=(100, 10)),
                                response("Order 37065 is overdue.", usage=(150, 20)))
    runner = RecordingRunner()
    outcome = answer_question("Where is 37065?", provider=provider, config=CONFIG,
                              as_of=date(2016, 6, 30), runner=runner)
    assert runner.calls == [("get_order_timeline", {"order_id": 37065, "as_of": "2016-06-30"})]
    assert outcome.answer == "Order 37065 is overdue."
    assert (outcome.input_tokens, outcome.output_tokens) == (250, 30)


def test_malformed_json_arguments_reach_validation_and_are_rejected() -> None:
    calls = [tool_call("c1", "get_order_timeline", '{"order_id": ')]
    provider, _ = provider_with(response(None, calls, finish="tool_calls"), response("sorry"))
    runner = RecordingRunner()
    outcome = answer_question("q", provider=provider, config=CONFIG, as_of=date(2016, 6, 30),
                              runner=runner)
    assert runner.calls == []
    assert outcome.tool_calls[0]["error_code"] == "INVALID_ARGUMENT"


# --- error mapping ------------------------------------------------------------------


@pytest.mark.parametrize("cls,status,retryable", [
    (openai.RateLimitError, 429, True),
    (openai.InternalServerError, 500, True),
    (openai.InternalServerError, 503, True),
    (openai.BadRequestError, 400, False),
    (openai.AuthenticationError, 401, False),
    (openai.PermissionDeniedError, 403, False),
    (openai.NotFoundError, 404, False),
    (openai.APIStatusError, 413, False),
    (openai.UnprocessableEntityError, 422, False),
])
def test_status_errors_are_classified(cls, status, retryable) -> None:
    error = to_model_error(status_error(cls, status))
    assert error.retryable is retryable
    assert error.error_class == cls.__name__
    assert str(error) == f"{cls.__name__} (status {status})"
    assert error.retry_after_s is None


def test_timeout_and_connection_errors_are_retryable() -> None:
    request = httpx2.Request("POST", URL)
    for exc in (openai.APITimeoutError(request=request), openai.APIConnectionError(request=request)):
        error = to_model_error(exc)
        assert error.retryable is True and error.error_class == type(exc).__name__


def test_rate_limit_retry_after_header_is_parsed() -> None:
    error = to_model_error(status_error(openai.RateLimitError, 429, {"retry-after": "7"}))
    assert error.retryable and error.retry_after_s == 7.0
    error = to_model_error(status_error(openai.RateLimitError, 429, {"retry-after-ms": "1500"}))
    assert error.retry_after_s == 1.5


def test_other_sdk_errors_are_not_retryable() -> None:
    error = to_model_error(openai.OpenAIError("boom"))
    assert error.retryable is False and error.error_class == "OpenAIError"


def test_next_turn_raises_mapped_error_without_secrets() -> None:
    exc = status_error(openai.AuthenticationError, 401)
    provider, _ = provider_with(exc)
    with pytest.raises(ModelError) as info:
        provider.next_turn(provider.start("s", [], "q"), allow_tools=True)
    assert info.value.error_class == "AuthenticationError" and not info.value.retryable
    assert FAKE_KEY not in str(info.value) and "error body" not in str(info.value)


def test_loop_turns_deepseek_error_into_fixed_message() -> None:
    provider, _ = provider_with(status_error(openai.InternalServerError, 503))
    outcome = answer_question("q", provider=provider, config=CONFIG, as_of=date(2016, 6, 30),
                              runner=RecordingRunner())
    assert outcome.answer == MODEL_ERROR_MESSAGE
    assert outcome.model_error == "InternalServerError (status 503)"


# --- model_errors helpers -------------------------------------------------------------


def test_is_retryable_status() -> None:
    assert all(is_retryable_status(s) for s in (408, 429, 500, 502, 503, 504, 529))
    assert not any(is_retryable_status(s) for s in (400, 401, 403, 404, 409, 413, 422))


def test_parse_retry_after_variants() -> None:
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after({"Retry-After": "3"}) == 3.0
    assert parse_retry_after({"retry-after": "0.5"}) == 0.5
    assert parse_retry_after({"retry-after-ms": "250", "retry-after": "9"}) == 0.25
    assert parse_retry_after({"retry-after-ms": "x", "retry-after": "9"}) == 9.0
    assert parse_retry_after({"retry-after": "Sat, 10 Oct 2026 12:00:30 GMT"}, now) == 30.0
    assert parse_retry_after({"retry-after": "Sat, 10 Oct 2026 11:00:00 GMT"}, now) == 0.0
    assert parse_retry_after({"retry-after": "-1"}) is None
    assert parse_retry_after({"retry-after": "soon"}) is None
    assert parse_retry_after({}) is None
    assert parse_retry_after(None) is None
    assert parse_retry_after(httpx2.Headers({"Retry-After": "4"})) == 4.0


def test_model_error_defaults_keep_old_behaviour() -> None:
    error = ModelError("APITimeoutError")
    assert error.error_class == "APITimeoutError"
    assert error.retryable is False and error.retry_after_s is None


# --- wiring -----------------------------------------------------------------------------


def test_factory_and_config_for_deepseek() -> None:
    provider = build_provider(CONFIG, {"DEEPSEEK_API_KEY": FAKE_KEY})
    assert isinstance(provider, DeepSeekProvider)
    assert provider.model_name == "deepseek-chat"
    assert str(provider._client.base_url).rstrip("/") == DEEPSEEK_BASE_URL
    assert provider._client.max_retries == 0
    assert api_key_for("deepseek", {"DEEPSEEK_API_KEY": FAKE_KEY}) == FAKE_KEY
    assert secret_values({"DEEPSEEK_API_KEY": FAKE_KEY}) == [FAKE_KEY]
    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY"):
        build_provider(CONFIG, {})
