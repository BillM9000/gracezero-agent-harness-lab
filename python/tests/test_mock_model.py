from __future__ import annotations

import pytest

from helpdesk.model.mock import MockModel, MockScriptExhausted
from helpdesk.model.types import Message, ModelResponse, ToolCall


def test_returns_scripted_responses_in_order_and_records_calls():
    model = MockModel(
        [
            ModelResponse(
                stop_reason="tool_use", tool_calls=(ToolCall("call_1", "search_kb", {"query": "password"}),)
            ),
            ModelResponse(stop_reason="end_turn", text="Try the reset link."),
        ]
    )
    question = [Message("user", "I can't log in")]
    first = model.complete(system="You are a helpdesk assistant.", messages=question)
    second = model.complete(system="You are a helpdesk assistant.", messages=question)

    assert first.stop_reason == "tool_use"
    assert first.tool_calls[0].name == "search_kb"
    assert second.text == "Try the reset link."
    assert len(model.calls) == 2
    assert model.calls[0].messages[0].content == "I can't log in"


def test_running_past_the_script_fails_with_a_fix():
    model = MockModel([ModelResponse(stop_reason="end_turn", text="ok")])
    model.complete(system="s", messages=[])
    with pytest.raises(MockScriptExhausted, match="Add a response to the script"):
        model.complete(system="s", messages=[])
