"""A ModelClient backed by Anthropic's Messages API.

This is the only file that knows the vendor's request and response shapes. It needs the anthropic
package and a credential the SDK can find, such as the ANTHROPIC_API_KEY environment variable.
Everything else in the lab talks to the ModelClient protocol, so the mock and this client are
interchangeable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from helpdesk.model.types import Message, ModelResponse, ToolCall, ToolSpec

# The model Anthropic's models page suggested starting with on 2026-09-22.
DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicModel:
    def __init__(self, client: Any = None, model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> None:
        if client is None:
            import anthropic  # imported here so code that only uses the mock never needs the SDK

            client = anthropic.Anthropic()
        self._client = client
        self.model = model
        self.max_tokens = max_tokens

    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [to_api(m) for m in messages],
        }
        if tools:
            request["tools"] = [tool_to_api(t) for t in tools]
        response = self._client.messages.create(**request)
        return ModelResponse(
            stop_reason=response.stop_reason,
            text="".join(block.text for block in response.content if block.type == "text"),
            tool_calls=tuple(
                ToolCall(block.id, block.name, dict(block.input))
                for block in response.content
                if block.type == "tool_use"
            ),
            raw=response.content,
        )


def tool_to_api(tool: ToolSpec) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}


def to_api(message: Message) -> dict[str, Any]:
    if message.role == "assistant":
        if message.raw is not None:
            # Send the model's own turn back exactly as it came, including any blocks this lab
            # doesn't model, such as thinking.
            return {"role": "assistant", "content": message.raw}
        blocks: list[dict[str, Any]] = [{"type": "text", "text": message.content}] if message.content else []
        blocks += [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in message.tool_calls
        ]
        return {"role": "assistant", "content": blocks}
    if message.tool_results:
        # Every result for a turn goes back in one user message.
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content}
                | ({"is_error": True} if r.is_error else {})
                for r in message.tool_results
            ],
        }
    return {"role": "user", "content": message.content}
