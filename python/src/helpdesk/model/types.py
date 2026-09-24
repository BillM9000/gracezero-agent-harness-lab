"""The shapes every model client speaks, real or mock. Nothing here names a vendor."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant"]
# Why the model stopped. These are the values Anthropic's "Stop reasons and fallback" page listed
# on 2026-09-22; other vendors use different names for the same ideas.
StopReason = Literal[
    "end_turn",
    "max_tokens",
    "stop_sequence",
    "tool_use",
    "pause_turn",
    "refusal",
    "model_context_window_exceeded",
]


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may ask to call. input_schema is JSON Schema.

    strict asks the provider to constrain the model's arguments to the schema, where it offers that
    (chapter 11). It never replaces checking the arguments before the tool runs: a provider's strict
    mode supports only part of JSON Schema, and a well-formed argument can still name a ticket that
    doesn't exist.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    strict: bool = False


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asked to run. The id pairs the call with its result."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """What running a tool produced. is_error tells the model the call failed, so it can adjust."""

    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """One turn of the conversation.

    A user turn carries text or, after the model called tools, their results. An assistant turn
    carries the model's text and tool calls, plus raw: the provider's own copy of the turn, which
    a real client sends back unchanged on the next call.
    """

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    raw: Any = None


@dataclass(frozen=True)
class ModelResponse:
    stop_reason: StopReason
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    raw: Any = None


class ModelClient(Protocol):
    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse: ...
