"""The Anthropic adapter, checked against a fake client. No network, no key.

These tests pin the request this code builds and how it reads a response. They do not prove the
real API accepts the request; only a call with a real key can do that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from helpdesk.assistant.narrow import narrow_tools
from helpdesk.assistant.tools import triage_tools
from helpdesk.model.anthropic_client import (
    DEFAULT_MODEL,
    MAX_STRICT_TOOLS,
    STRICT_UNSUPPORTED,
    AnthropicModel,
    strict_schema,
    tool_to_api,
)
from helpdesk.model.types import Message, ToolCall, ToolResult, ToolSpec
from helpdesk.services.access import Person


@dataclass
class Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    stop_reason: str
    content: list[Block]


class FakeMessages:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def create(self, **request: Any) -> Response:
        self.requests.append(request)
        return self.response


class FakeClient:
    def __init__(self, response: Response) -> None:
        self.messages = FakeMessages(response)


TOOL = ToolSpec(
    "get_ticket", "Read a ticket.", {"type": "object", "properties": {"ticket_id": {"type": "integer"}}}
)


def test_the_request_carries_model_system_tools_and_messages():
    client = FakeClient(Response("end_turn", [Block("text", text="hi")]))
    AnthropicModel(client).complete(system="be brief", messages=[Message("user", "hello")], tools=[TOOL])
    [request] = client.messages.requests
    assert request["model"] == DEFAULT_MODEL == "claude-opus-5-5"
    assert request["system"] == "be brief"
    assert request["messages"] == [{"role": "user", "content": "hello"}]
    assert request["tools"] == [
        {"name": "get_ticket", "description": "Read a ticket.", "input_schema": TOOL.input_schema}
    ]


def test_no_tools_means_no_tools_parameter():
    client = FakeClient(Response("end_turn", [Block("text", text="hi")]))
    AnthropicModel(client).complete(system="s", messages=[Message("user", "hello")])
    assert "tools" not in client.messages.requests[0]


def test_a_response_becomes_text_tool_calls_and_the_raw_blocks():
    content = [
        Block("text", text="Let me look. "),
        Block("tool_use", id="toolu_1", name="get_ticket", input={"ticket_id": 1}),
    ]
    response = AnthropicModel(FakeClient(Response("tool_use", content))).complete(system="s", messages=[])
    assert response.stop_reason == "tool_use"
    assert response.text == "Let me look. "
    assert response.tool_calls == (ToolCall("toolu_1", "get_ticket", {"ticket_id": 1}),)
    assert response.raw is content


def test_the_models_own_turn_is_sent_back_unchanged():
    raw = [Block("thinking"), Block("tool_use", id="toolu_1", name="get_ticket", input={"ticket_id": 1})]
    client = FakeClient(Response("end_turn", [Block("text", text="ok")]))
    turn = Message("assistant", tool_calls=(ToolCall("toolu_1", "get_ticket", {"ticket_id": 1}),), raw=raw)
    AnthropicModel(client).complete(system="s", messages=[Message("user", "t"), turn])
    assert client.messages.requests[0]["messages"][1] == {"role": "assistant", "content": raw}


def test_tool_results_go_back_in_one_user_message_with_errors_flagged():
    results = (
        ToolResult("toolu_1", "Ticket 1 ..."),
        ToolResult("toolu_2", "ticket 999 does not exist", is_error=True),
    )
    client = FakeClient(Response("end_turn", [Block("text", text="ok")]))
    AnthropicModel(client).complete(system="s", messages=[Message("user", tool_results=results)])
    assert client.messages.requests[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Ticket 1 ..."},
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_2",
                    "content": "ticket 999 does not exist",
                    "is_error": True,
                },
            ],
        }
    ]


# Strict tool use (chapter 11). These pin the request the adapter builds for a strict tool; only a
# call with a real key could show the API accepting it, and the lab doesn't make one.

STRICT = ToolSpec(
    "find_tickets",
    "Find tickets.",
    {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["open", "closed"], "description": "Which ones."},
            "page": {"type": "integer", "minimum": 1, "maximum": 50, "description": "From 1."},
            "query": {"type": "string", "minLength": 1, "maxLength": 200, "description": "Words."},
        },
        "required": [],
        "additionalProperties": False,
    },
    strict=True,
)


def keys_in(value):
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_in(v)}
    return set()


def test_a_strict_tool_goes_out_marked_strict_without_the_keywords_strict_mode_refuses():
    sent = tool_to_api(STRICT)
    assert sent["strict"] is True
    assert not keys_in(sent["input_schema"]) & set(STRICT_UNSUPPORTED)
    assert sent["input_schema"]["properties"]["page"] == {"type": "integer", "description": "From 1."}
    assert sent["input_schema"]["properties"]["status"]["enum"] == ["open", "closed"]
    assert sent["input_schema"]["additionalProperties"] is False
    # The lab's own copy keeps them: the toolbox enforces what strict mode can't.
    assert STRICT.input_schema["properties"]["page"]["minimum"] == 1


def test_a_tool_that_is_not_strict_goes_out_as_written():
    assert tool_to_api(TOOL) == {
        "name": "get_ticket",
        "description": "Read a ticket.",
        "input_schema": TOOL.input_schema,
    }


def test_a_property_named_like_a_keyword_is_kept():
    schema = {
        "type": "object",
        "properties": {"minimum": {"type": "integer", "minimum": 0}},
        "additionalProperties": False,
    }
    assert strict_schema(schema)["properties"] == {"minimum": {"type": "integer"}}


def test_a_strict_object_that_allows_extra_properties_is_refused_before_sending():
    loose = ToolSpec("t", "T.", {"type": "object", "properties": {"n": {"type": "integer"}}}, strict=True)
    client = FakeClient(Response("end_turn", [Block("text", text="hi")]))
    with pytest.raises(ValueError, match=r"^t: strict tool use needs additionalProperties set to false"):
        AnthropicModel(client).complete(system="s", messages=[Message("user", "hi")], tools=[loose])
    assert client.messages.requests == []


def test_more_strict_tools_than_one_request_may_carry_are_refused_before_sending():
    tools = [ToolSpec(f"t{i}", "T.", STRICT.input_schema, strict=True) for i in range(MAX_STRICT_TOOLS + 1)]
    client = FakeClient(Response("end_turn", [Block("text", text="hi")]))
    with pytest.raises(ValueError, match="21 strict tools in one request, and strict tool use allows 20"):
        AnthropicModel(client).complete(system="s", messages=[Message("user", "hi")], tools=tools)
    assert client.messages.requests == []


def test_every_tool_the_lab_defines_goes_out_in_a_form_strict_mode_accepts(conn):
    anyone = Person(1, "Any One", "support")
    for build in (triage_tools, narrow_tools):
        specs = build(conn, anyone).specs
        optional = 0
        for spec in specs:
            sent = tool_to_api(spec)
            assert sent["strict"] is True, spec.name
            assert not keys_in(sent["input_schema"]) & set(STRICT_UNSUPPORTED), spec.name
            schema = sent["input_schema"]
            optional += len(set(schema["properties"]) - set(schema.get("required", [])))
        # Anthropic's limits on strict schemas in one request, as documented on 2026-09-23.
        assert len(specs) <= MAX_STRICT_TOOLS
        assert optional <= 24
