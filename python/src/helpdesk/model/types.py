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
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may ask to call. input_schema is JSON Schema."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    stop_reason: StopReason
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


class ModelClient(Protocol):
    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse: ...
