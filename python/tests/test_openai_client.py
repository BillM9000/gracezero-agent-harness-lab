"""The OpenAI adapter, checked against a fake client. No network, no key.

These tests pin the request this code builds and how it reads a response, in the shapes openai 3.22.1
and OpenAI's API reference gave on 2026-10-01. They do not prove the real API accepts the request;
only a call with a real key can do that.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from helpdesk.assistant.narrow import narrow_tools
from helpdesk.assistant.tools import triage_tools
from helpdesk.model.mock import FakeProviderClient, as_anthropic, as_openai
from helpdesk.model.openai_client import (
    DEFAULT_MODEL,
    OpenAIModel,
    qualifies,
    read_response,
    to_api,
    tool_to_api,
)
from helpdesk.model.stops import NotFinished, final_text
from helpdesk.model.types import Message, ModelResponse, ToolCall, ToolResult, ToolSpec, Unavailable, Usage
from helpdesk.services.access import Person

TOOL = ToolSpec(
    "get_ticket", "Read a ticket.", {"type": "object", "properties": {"ticket_id": {"type": "integer"}}}
)


def test_the_request_carries_model_instructions_input_tools_and_the_cap():
    fake = FakeProviderClient([ModelResponse("end_turn", "hi")])
    OpenAIModel(fake, max_tokens=1000).complete(
        system="be brief", messages=[Message("user", "hello")], tools=[TOOL]
    )
    [(api, request)] = fake.requests
    assert api == "responses.create"
    assert request["model"] == DEFAULT_MODEL == "gpt-6.1-sol"
    assert request["instructions"] == "be brief"
    assert request["max_output_tokens"] == 1000
    assert request["input"] == [{"role": "user", "content": "hello"}]
    assert request["tools"] == [
        {
            "type": "function",
            "name": "get_ticket",
            "description": "Read a ticket.",
            "parameters": TOOL.input_schema,
            "strict": False,
        }
    ]


def test_no_tools_means_no_tools_parameter():
    fake = FakeProviderClient([ModelResponse("end_turn", "hi")])
    OpenAIModel(fake).complete(system="s", messages=[Message("user", "hello")])
    assert "tools" not in fake.requests[0][1]


def test_a_response_becomes_text_tool_calls_and_the_raw_items():
    output = [
        SimpleNamespace(type="reasoning", summary=[]),
        SimpleNamespace(
            type="message",
            role="assistant",
            content=[SimpleNamespace(type="output_text", text="Let me look. ")],
        ),
        SimpleNamespace(
            type="function_call", call_id="call_1", name="get_ticket", arguments='{"ticket_id": 1}'
        ),
    ]
    response = read_response(
        SimpleNamespace(status="completed", incomplete_details=None, output=output, usage=None)
    )
    assert response.stop_reason == "tool_use"
    assert response.text == "Let me look. "
    assert response.tool_calls == (ToolCall("call_1", "get_ticket", {"ticket_id": 1}),)
    assert response.raw == output  # the reasoning item included, to go back on the next turn


def test_a_refusal_part_is_a_refusal_and_a_cut_off_answer_is_max_tokens():
    assert (
        read_response(as_openai(ModelResponse("refusal", "I can't help with that."))).stop_reason == "refusal"
    )
    cut = read_response(as_openai(ModelResponse("max_tokens", "Half an")))
    assert (cut.stop_reason, cut.text) == ("max_tokens", "Half an")

    def incomplete(reason: str) -> Any:
        return SimpleNamespace(
            status="incomplete", incomplete_details=SimpleNamespace(reason=reason), output=[], usage=None
        )

    assert read_response(incomplete("content_filter")).stop_reason == "refusal"
    # A cap on messages or a WebSocket steer, which the lab never uses: unfinished, never an answer.
    steered = read_response(incomplete("steered"))
    assert steered.stop_reason == "pause_turn"
    with pytest.raises(NotFinished):
        final_text(steered)


def test_a_response_that_isnt_an_answer_is_an_error_not_a_blank_answer():
    failed = SimpleNamespace(
        status="failed",
        error=SimpleNamespace(code="server_error", message="try again"),
        incomplete_details=None,
        output=[],
        usage=None,
    )
    with pytest.raises(
        RuntimeError, match="status 'failed' \\(server_error: try again\\), which isn't an answer"
    ):
        read_response(failed)
    with pytest.raises(RuntimeError, match="status 'in_progress'"):
        read_response(SimpleNamespace(status="in_progress", incomplete_details=None, output=[], usage=None))


def test_usage_and_the_request_id_are_passed_on():
    fake = FakeProviderClient([ModelResponse("end_turn", "hi", usage=Usage(12, 3), request_id="resp_abc")])
    response = OpenAIModel(fake).complete(system="s", messages=[Message("user", "hi")])
    assert (response.usage, response.request_id) == (Usage(12, 3), "resp_abc")
    assert (
        OpenAIModel(FakeProviderClient([ModelResponse("end_turn", "hi")]))
        .complete(system="s", messages=[])
        .usage
        is None
    )


def test_the_models_own_turn_is_sent_back_as_the_items_it_came_as():
    raw = [SimpleNamespace(type="reasoning"), SimpleNamespace(type="function_call", call_id="call_1")]
    turn = Message("assistant", tool_calls=(ToolCall("call_1", "get_ticket", {"ticket_id": 1}),), raw=raw)
    fake = FakeProviderClient([ModelResponse("end_turn", "ok")])
    OpenAIModel(fake).complete(system="s", messages=[Message("user", "t"), turn])
    assert fake.requests[0][1]["input"] == [{"role": "user", "content": "t"}, *raw]


def test_an_assistant_turn_without_raw_is_sent_as_text_and_function_calls():
    turn = Message(
        "assistant", "Let me look.", tool_calls=(ToolCall("call_1", "get_ticket", {"ticket_id": 1}),)
    )
    assert to_api(turn) == [
        {"role": "assistant", "content": "Let me look."},
        {"type": "function_call", "call_id": "call_1", "name": "get_ticket", "arguments": '{"ticket_id": 1}'},
    ]


def test_tool_results_go_back_as_function_call_outputs_and_an_error_says_so_in_words():
    results = (
        ToolResult("call_1", "Ticket 1 ..."),
        ToolResult("call_2", "ticket 999 does not exist", is_error=True),
    )
    assert to_api(Message("user", tool_results=results)) == [
        {"type": "function_call_output", "call_id": "call_1", "output": "Ticket 1 ..."},
        {"type": "function_call_output", "call_id": "call_2", "output": "Error: ticket 999 does not exist"},
    ]


def test_arguments_that_arent_a_json_object_are_refused():
    call = SimpleNamespace(type="function_call", call_id="c", name="get_ticket", arguments="[1]")
    bad = SimpleNamespace(status="completed", incomplete_details=None, output=[call], usage=None)
    with pytest.raises(ValueError, match="get_ticket's arguments aren't a JSON object"):
        read_response(bad)
    call.arguments = "{not json"
    with pytest.raises(ValueError, match="get_ticket's arguments aren't JSON"):
        read_response(bad)


# Strict mode (chapter 11), as OpenAI's function calling guide stated it on 2026-10-01: every object
# sets additionalProperties to false and lists every property as required.

QUALIFYING = ToolSpec(
    "close_ticket",
    "Close one.",
    {
        "type": "object",
        "properties": {"ticket_id": {"type": "integer"}, "reason": {"type": ["string", "null"]}},
        "required": ["ticket_id", "reason"],
        "additionalProperties": False,
    },
    strict=True,
)
OPTIONAL = ToolSpec(
    "find_tickets",
    "Find some.",
    {
        "type": "object",
        "properties": {"status": {"type": "string"}, "page": {"type": "integer", "minimum": 1}},
        "required": [],
        "additionalProperties": False,
    },
    strict=True,
)


def test_strict_goes_out_only_for_a_schema_the_apis_strict_mode_accepts():
    assert tool_to_api(QUALIFYING)["strict"] is True
    assert tool_to_api(QUALIFYING)["parameters"] == QUALIFYING.input_schema  # sent as written
    # Optional properties: strict would be refused, and left out the API would rewrite the schema.
    assert tool_to_api(OPTIONAL)["strict"] is False
    assert tool_to_api(TOOL)["strict"] is False  # not asked for
    assert qualifies({"type": "object", "properties": {}, "required": [], "additionalProperties": False})
    assert not qualifies({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    nested = {
        "type": "object",
        "properties": {"inner": {"type": "object", "properties": {"b": {"type": "integer"}}, "required": []}},
        "required": ["inner"],
        "additionalProperties": False,
    }
    assert not qualifies(nested)
    # A property named like a keyword is data.
    named = {
        "type": "object",
        "properties": {"required": {"type": "integer"}},
        "required": ["required"],
        "additionalProperties": False,
    }
    assert qualifies(named)


def test_every_tool_the_lab_defines_goes_out_as_a_function_tool_with_its_schema_as_written(conn):
    anyone = Person(1, "Any One", "support")
    for build in (triage_tools, narrow_tools):
        for spec in build(conn, anyone).specs:
            sent = tool_to_api(spec)
            assert (sent["type"], sent["name"], sent["parameters"]) == (
                "function",
                spec.name,
                spec.input_schema,
            )
            assert sent["strict"] is qualifies(spec.input_schema), spec.name


# What counts as an outage (chapter 27), from openai 3.22.1's exception classes.


class StatusError(Exception):
    def __init__(self, status: int, retry: str | None = None) -> None:
        super().__init__(status)
        self.status_code = status
        self.response = SimpleNamespace(headers={"retry-after": retry} if retry else {})


class APIConnectionError(Exception):
    pass


class APITimeoutError(APIConnectionError):
    pass


@pytest.mark.parametrize(
    ("error", "kind", "wait"),
    [
        (StatusError(429, "12"), "rate limited", 12.0),
        (StatusError(429), "rate limited", None),
        (StatusError(500), "server error", None),
        (StatusError(503), "server error", None),
        (APITimeoutError("slow"), "no connection", None),
    ],
)
def test_an_outage_from_the_provider_becomes_unavailable_with_its_wait(error, kind, wait):
    def create(**_: Any) -> Any:
        raise error

    model = OpenAIModel(SimpleNamespace(responses=SimpleNamespace(create=create)))
    with pytest.raises(Unavailable) as down:
        model.complete(system="s", messages=[Message("user", "hi")])
    assert (down.value.kind, down.value.retry_after) == (kind, wait)


def test_a_request_the_provider_rejects_is_raised_as_it_is():
    def create(**_: Any) -> Any:
        raise StatusError(400)

    with pytest.raises(StatusError):
        OpenAIModel(SimpleNamespace(responses=SimpleNamespace(create=create))).complete(
            system="s", messages=[Message("user", "hi")]
        )


# The fake behind both adapters.


def test_the_fake_client_plays_one_script_in_either_sdks_shape():
    script = [ModelResponse("end_turn", "one", usage=Usage(1, 2)), ModelResponse("refusal")]
    fake = FakeProviderClient(script)
    first = fake.messages.create(model="m", messages=[])
    assert (first.stop_reason, first.content[0].text, first.usage.input_tokens) == ("end_turn", "one", 1)
    second = fake.responses.create(model="m", input=[])
    assert (second.status, second.output[0].content[0].type) == ("completed", "refusal")
    assert [api for api, _ in fake.requests] == ["messages.create", "responses.create"]
    with pytest.raises(RuntimeError, match="called 3 times but its script has 2"):
        fake.responses.create(model="m", input=[])
    # Each shape reads back as the response it played.
    for response in script:
        assert read_response(as_openai(response)).stop_reason == response.stop_reason
        assert as_anthropic(response).stop_reason == response.stop_reason
