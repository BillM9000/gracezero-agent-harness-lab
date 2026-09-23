"""A deterministic stand-in for a real model.

It returns scripted responses in order and records every call, so tests and labs run
the same way every time, offline, for free.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

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
