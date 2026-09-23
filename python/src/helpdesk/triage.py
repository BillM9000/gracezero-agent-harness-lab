"""Composition root for the triage assistant's command line.

python -m helpdesk.triage                  the scripted demo, with the mock model
python -m helpdesk.triage --max-turns 2    the same demo, stopped by the turn limit
python -m helpdesk.triage --real "Ticket 3: what should we tell this customer?"

--real calls Anthropic's API and needs a credential the SDK can find, such as ANTHROPIC_API_KEY.
Each run uses a fresh in-memory copy of the sample data, so nothing is saved.
"""

from __future__ import annotations

import argparse
import json
import sys

from helpdesk.assistant.agent import TurnLimitReached, run_agent
from helpdesk.assistant.tools import triage_tools
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed
from helpdesk.model.mock import MockModel
from helpdesk.model.stops import IncompleteResponse
from helpdesk.model.types import Message, ModelClient, ModelResponse, ToolCall

SYSTEM = (
    "You are the triage assistant for a small software company's helpdesk. Use the tools to read "
    "the ticket and search the knowledge base before you answer. Then draft a short reply to the "
    "customer for a member of staff to review. You never send replies or change tickets yourself. "
    "If the knowledge base doesn't cover the problem, say so instead of guessing."
)

DEMO_TASK = "Ticket 1: the customer says the reset email never arrives. Draft a reply."

# The mock plays the model's part from a fixed script. The loop, the tools and the stop
# conditions around it are the real code.
DEMO_SCRIPT = [
    ModelResponse("tool_use", tool_calls=(ToolCall("call_1", "get_ticket", {"ticket_id": 1}),)),
    ModelResponse("tool_use", tool_calls=(ToolCall("call_2", "search_kb", {"query": "password"}),)),
    ModelResponse(
        "end_turn",
        text=(
            "Hello, and sorry for the trouble. Reset emails can take up to ten minutes to arrive, and "
            "they sometimes land in the spam folder. Please check your spam folder, then use the "
            "Forgot password link once more. If nothing arrives within ten minutes, reply here and "
            "we'll look into it."
        ),
    ),
]


def print_transcript(transcript: tuple[Message, ...]) -> None:
    turn = 0
    for message in transcript[1:]:
        if message.role == "assistant":
            turn += 1
            for call in message.tool_calls:
                print(f"turn {turn}  calls {call.name} {json.dumps(call.arguments)}")
        for result in message.tool_results:
            label = "error" if result.is_error else "result"
            for i, line in enumerate(result.content.splitlines()):
                print(f"        {label + ':' if i == 0 else ' ' * (len(label) + 1)} {line}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.triage")
    parser.add_argument("task", nargs="?", help="what to ask the assistant (needs --real)")
    parser.add_argument("--real", action="store_true", help="use Anthropic's API instead of the mock")
    parser.add_argument("--max-turns", type=int, default=6)
    args = parser.parse_args()
    if args.task and not args.real:
        parser.error("the mock only knows its demo script; add --real to ask your own question")

    conn = connect(":memory:")
    init_schema(conn)
    seed(conn)
    model: ModelClient
    if args.real:
        from helpdesk.model.anthropic_client import AnthropicModel

        model, task, label = AnthropicModel(), args.task or DEMO_TASK, "Anthropic API"
    else:
        model, task, label = MockModel(DEMO_SCRIPT), DEMO_TASK, "mock, scripted"

    print(f"Task: {task}\nModel: {label}\n")
    try:
        run = run_agent(model, triage_tools(conn), system=SYSTEM, task=task, max_turns=args.max_turns)
    except TurnLimitReached as stop:
        print_transcript(stop.transcript)
        print(f"\nStopped: {stop}")
        return 1
    except IncompleteResponse as stop:
        print(f"\nStopped: {stop}")
        return 1
    finally:
        conn.close()
    print_transcript(run.transcript)
    print(f"turn {run.turns}  answers:\n\n{run.answer}\n")
    print(f"Finished in {run.turns} turns (limit {args.max_turns}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
