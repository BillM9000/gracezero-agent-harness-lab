"""The smallest agent: a model in a loop with tools and a stop condition.

Each turn, the model either asks for tools or stops. When it asks, the loop runs the tools and
sends every result back in one message. When it stops, final_text decides whether the stop is a
finished answer. A turn limit ends the loop if the model never stops on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from helpdesk.assistant.tools import Toolbox
from helpdesk.model.stops import NotFinished, final_text
from helpdesk.model.types import Message, ModelClient


class TurnLimitReached(Exception):
    def __init__(self, max_turns: int, transcript: tuple[Message, ...]) -> None:
        super().__init__(
            f"No answer after {max_turns} turns: the model was still calling tools. Raise the limit "
            "if the task really needs more steps; otherwise read the transcript for a loop."
        )
        self.transcript = transcript


@dataclass(frozen=True)
class AgentRun:
    answer: str
    turns: int
    transcript: tuple[Message, ...]


def run_agent(model: ModelClient, tools: Toolbox, *, system: str, task: str, max_turns: int = 6) -> AgentRun:
    messages: list[Message] = [Message("user", task)]
    for turn in range(1, max_turns + 1):
        response = model.complete(system=system, messages=messages, tools=tools.specs)
        messages.append(Message("assistant", response.text, tool_calls=response.tool_calls, raw=response.raw))
        if response.stop_reason != "tool_use":
            # A finished answer, or an exception that says why it isn't one.
            return AgentRun(final_text(response), turn, tuple(messages))
        if not response.tool_calls:
            raise NotFinished("The model stopped to use a tool but named none. Treat the turn as unfinished.")
        results = tuple(tools.run(call) for call in response.tool_calls)
        messages.append(Message("user", tool_results=results))
    raise TurnLimitReached(max_turns, tuple(messages))
