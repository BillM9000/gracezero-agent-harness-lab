"""A deterministic stand-in for a real model.

It returns scripted responses in order and records every call, so tests and labs run
the same way every time, offline, for free.

FakeProviderClient, below, stands one level lower: in a provider's SDK client's place, playing the
same scripted responses in each SDK's own response shape, so the adapters and the --real path can be
tested with no key and no network.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from helpdesk.model.types import Message, ModelResponse, ToolSpec


class MockScriptExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class MockCall:
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]


class MockModel:
    def __init__(self, script: Iterable[ModelResponse]) -> None:
        self._script = list(script)
        self.calls: list[MockCall] = []

    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse:
        self.calls.append(MockCall(system=system, messages=tuple(messages), tools=tuple(tools)))
        if len(self.calls) > len(self._script):
            raise MockScriptExhausted(
                f"MockModel was called {len(self.calls)} times but its script has "
                f"{len(self._script)} responses. Add a response to the script, or look for a "
                "loop that never reaches a stop condition."
            )
        return self._script[len(self.calls) - 1]


# --- A provider's SDK client, faked.


def as_anthropic(response: ModelResponse) -> Any:
    """The response in the shape anthropic_client.py reads: stop_reason, content blocks of text and
    tool_use, usage and _request_id."""
    content: list[Any] = [SimpleNamespace(type="text", text=response.text)] if response.text else []
    content += [
        SimpleNamespace(type="tool_use", id=c.id, name=c.name, input=dict(c.arguments))
        for c in response.tool_calls
    ]
    return SimpleNamespace(
        stop_reason=response.stop_reason,
        content=content,
        usage=usage_of(response),
        _request_id=response.request_id,
    )


def as_openai(response: ModelResponse) -> Any:
    """The response in the shape openai_client.py reads: status, incomplete_details, output items (a
    message of output_text or refusal parts, function_call items), usage, error and _request_id. The
    shape has no stop_sequence or pause_turn, so a response stopped that way plays as completed."""
    parts: list[Any] = []
    if response.stop_reason == "refusal":
        parts.append(SimpleNamespace(type="refusal", refusal=response.text))
    elif response.text:
        parts.append(SimpleNamespace(type="output_text", text=response.text))
    output: list[Any] = [SimpleNamespace(type="message", role="assistant", content=parts)] if parts else []
    output += [
        SimpleNamespace(type="function_call", call_id=c.id, name=c.name, arguments=json.dumps(c.arguments))
        for c in response.tool_calls
    ]
    cut = response.stop_reason in ("max_tokens", "model_context_window_exceeded")
    return SimpleNamespace(
        status="incomplete" if cut else "completed",
        incomplete_details=SimpleNamespace(reason="max_output_tokens") if cut else None,
        output=output,
        usage=usage_of(response),
        error=None,
        _request_id=response.request_id,
    )


def usage_of(response: ModelResponse) -> Any:
    if response.usage is None:
        return None
    return SimpleNamespace(
        input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
    )


class FakeProviderClient:
    """A stand-in for a provider's SDK client, for tests of the adapters and of the --real path. It
    plays scripted ModelResponses in each SDK's own response shape, as the lab's adapters read them,
    and records every request: messages.create answers in the shape anthropic_client.py reads, and
    responses.create in the shape openai_client.py reads, both from the one script in call order, so
    one fake can stand behind every provider in a run. The shapes are plain objects with the attributes
    the adapters read and nothing more: what the SDKs really return is proved only by a call with a
    key, which the lab never makes."""

    def __init__(self, script: Iterable[ModelResponse]) -> None:
        self._script = list(script)
        self.requests: list[tuple[str, dict[str, Any]]] = []  # which API was called, and with what
        self.messages = SimpleNamespace(create=self._api("messages.create", as_anthropic))
        self.responses = SimpleNamespace(create=self._api("responses.create", as_openai))

    def _api(self, name: str, shape: Callable[[ModelResponse], Any]) -> Callable[..., Any]:
        def create(**request: Any) -> Any:
            self.requests.append((name, request))
            if len(self.requests) > len(self._script):
                raise MockScriptExhausted(
                    f"FakeProviderClient was called {len(self.requests)} times but its script has "
                    f"{len(self._script)} responses. Add a response to the script."
                )
            return shape(self._script[len(self.requests) - 1])

        return create
