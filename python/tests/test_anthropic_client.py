"""The Anthropic adapter, checked against a fake client. No network, no key.

These tests pin the request this code builds and how it reads a response. They do not prove the
real API accepts the request; only a call with a real key can do that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from helpdesk.model.anthropic_client import DEFAULT_MODEL, AnthropicModel
from helpdesk.model.types import Message, ToolCall, ToolResult, ToolSpec


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
