from __future__ import annotations

import pytest

from helpdesk.assistant.agent import TurnLimitReached, run_agent
from helpdesk.assistant.tools import Tool, Toolbox
from helpdesk.model.mock import MockModel
from helpdesk.model.stops import NotFinished, Refused
from helpdesk.model.types import ModelResponse, ToolCall, ToolSpec

ECHO = Tool(
    ToolSpec(
        "echo",
        "Repeat the text.",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    ),
    lambda text: f"echo: {text}",
)


def asks(*calls: ToolCall) -> ModelResponse:
    return ModelResponse("tool_use", tool_calls=calls)


def test_the_loop_runs_tools_until_the_model_answers():
    model = MockModel([asks(ToolCall("c1", "echo", {"text": "hi"})), ModelResponse("end_turn", text="done")])
    run = run_agent(model, Toolbox([ECHO]), system="s", task="say hi")
    assert run.answer == "done"
    assert run.turns == 2
    assert [m.role for m in run.transcript] == ["user", "assistant", "user", "assistant"]


def test_the_model_sees_each_result_on_its_next_call_with_the_matching_id():
    model = MockModel([asks(ToolCall("c1", "echo", {"text": "hi"})), ModelResponse("end_turn", text="done")])
    run_agent(model, Toolbox([ECHO]), system="s", task="say hi")
    [result] = model.calls[1].messages[-1].tool_results
    assert (result.call_id, result.content, result.is_error) == ("c1", "echo: hi", False)


def test_every_result_for_a_turn_goes_back_in_one_message():
    calls = (ToolCall("c1", "echo", {"text": "a"}), ToolCall("c2", "echo", {"text": "b"}))
    model = MockModel([asks(*calls), ModelResponse("end_turn", text="done")])
    run_agent(model, Toolbox([ECHO]), system="s", task="twice")
    assert [r.call_id for r in model.calls[1].messages[-1].tool_results] == ["c1", "c2"]


def test_the_model_is_offered_the_tools_on_every_turn():
    model = MockModel([asks(ToolCall("c1", "echo", {"text": "a"})), ModelResponse("end_turn", text="done")])
    run_agent(model, Toolbox([ECHO]), system="s", task="t")
    assert all(call.tools == (ECHO.spec,) for call in model.calls)


def test_a_model_that_never_stops_is_stopped_by_the_turn_limit():
    model = MockModel([asks(ToolCall(f"c{n}", "echo", {"text": "again"})) for n in range(5)])
    with pytest.raises(TurnLimitReached, match="No answer after 3 turns") as stopped:
        run_agent(model, Toolbox([ECHO]), system="s", task="loop", max_turns=3)
    assert len(model.calls) == 3
    assert len(stopped.value.transcript) == 7  # the task, then a call and its results for each turn


def test_a_refusal_ends_the_run_instead_of_passing_as_an_answer():
    model = MockModel([asks(ToolCall("c1", "echo", {"text": "a"})), ModelResponse("refusal")])
    with pytest.raises(Refused):
        run_agent(model, Toolbox([ECHO]), system="s", task="t")


def test_a_tool_stop_with_no_tool_named_is_not_an_answer():
    with pytest.raises(NotFinished, match="named none"):
        run_agent(MockModel([ModelResponse("tool_use")]), Toolbox([ECHO]), system="s", task="t")
