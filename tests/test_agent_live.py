"""Optional live smoke test: calls the real model. Skipped unless RUN_LIVE=1."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1")


def test_live_lookup_of_missing_order() -> None:
    from agent.clock import read_clock, resolve_session_as_of
    from agent.config import load_config
    from agent.factory import build_provider
    from agent.loop import answer_question

    config = load_config(os.environ)
    provider = build_provider(config, os.environ)
    as_of = resolve_session_as_of(None, read_clock())
    outcome = answer_question(
        "Show me the timeline of order 99999999.",
        provider=provider, config=config, as_of=as_of,
    )
    assert outcome.stop == "final_answer"
    assert outcome.tool_calls and outcome.tool_calls[0]["error_code"] == "ORDER_NOT_FOUND"
    assert "99999999" in outcome.answer
