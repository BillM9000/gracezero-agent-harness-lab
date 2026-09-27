"""Composition root for the triage assistant's command line.

python -m helpdesk.triage                  the scripted demo, with the mock model
python -m helpdesk.triage --max-turns 2    the same demo, stopped by the turn limit
python -m helpdesk.triage --real "Ticket 3: what should we tell this customer?"
python -m helpdesk.triage --agent FILE     run another agent definition instead of agents/triage.toml

The assistant is built from its definition, agents/triage.toml, which must pass the platform's
policy (agents/policy.toml, chapter 18) before anything runs. --real calls Anthropic's API and
needs a credential the SDK can find, such as ANTHROPIC_API_KEY. Each run uses a fresh in-memory
copy of the sample data, so nothing is saved. After an answer, every citation in it is checked
against the passages the run's searches returned (chapter 9), and a problem makes the exit code 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_policy import AGENTS, POLICY, load
from agent_policy.rules import check
from helpdesk.assistant.agent import TurnLimitReached, run_agent
from helpdesk.assistant.tools import triage_tools
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed
from helpdesk.model.mock import MockModel
from helpdesk.model.stops import IncompleteResponse
from helpdesk.model.types import Message, ModelClient, ModelResponse, ToolCall
from helpdesk.services import citations, kb

DEMO_TASK = "Ticket 1: the customer says the reset email never arrives. Draft a reply."

# The mock plays the model's part from a fixed script. The loop, the tools and the stop
# conditions around it are the real code.
DEMO_SCRIPT = [
    ModelResponse("tool_use", tool_calls=(ToolCall("call_1", "get_ticket", {"ticket_id": 1}),)),
    ModelResponse(
        "tool_use", tool_calls=(ToolCall("call_2", "search_kb", {"query": "reset email never arrives"}),)
    ),
    ModelResponse(
        "end_turn",
        text=(
            "Hello, and sorry for the trouble. Reset emails can take up to ten minutes to arrive, and "
            "they sometimes land in the spam folder [1#2]. Check your spam folder, then use the Forgot "
            "password link again [1#2]. A reset link works once, and it expires 30 minutes after we "
            "send it [1#3]. If nothing arrives within ten minutes, reply here and we'll look into it."
        ),
    ),
]


def passages_given(transcript: tuple[Message, ...]) -> dict[str, str]:
    """Every passage the knowledge-base searches in this run showed the model, by id. The
    transcript is the record of what the model actually read, so citations are checked against
    it, not against the knowledge base as a whole."""
    searches = {call.id for message in transcript for call in message.tool_calls if call.name == "search_kb"}
    given: dict[str, str] = {}
    for message in transcript:
        for result in message.tool_results:
            if result.call_id in searches and not result.is_error:
                given.update(citations.passages_in(result.content))
    return given


def report_citations(answer: str, transcript: tuple[Message, ...], known: set[str]) -> bool:
    """Print what the citation check found (chapter 9). True when every citation holds up."""
    given = passages_given(transcript)
    report = citations.check(answer, given, known)
    against = f"against the passages this run was given ({', '.join(given) or 'none'})"
    if report.ok:
        print(f"Citations: {report.checked} checked {against}; all exist and use only their passages' words.")
    else:
        print(f"Citations: {len(report.problems)} problem(s), checked {against}:")
        for problem in report.problems:
            print(f"  {problem.reason}\n    in: {problem.sentence}")
    print(f"Not checked: {len(report.uncited)} sentence(s) cite nothing.")
    return report.ok


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
    parser.add_argument("--max-turns", type=int, help="this run's turn limit (default: the definition's)")
    parser.add_argument("--agent", type=Path, default=AGENTS / "triage.toml", help="the definition to run")
    args = parser.parse_args()
    if args.task and not args.real:
        parser.error("the mock only knows its demo script; add --real to ask your own question")

    # The policy checks what will actually run: the definition, with this run's --max-turns applied.
    agent = load(args.agent)
    if args.max_turns is not None:
        agent["max_turns"] = args.max_turns
    violations = check(agent, load(POLICY))
    if violations:
        for violation in violations:
            print(f"{violation.path}: {violation.reason}", file=sys.stderr)
        refused = "Refused: this agent breaks the platform's policy (agents/policy.toml). Nothing ran."
        print(refused, file=sys.stderr)
        return 2

    conn = connect(":memory:")
    init_schema(conn)
    seed(conn)
    model: ModelClient
    if args.real:
        from helpdesk.model.anthropic_client import AnthropicModel

        model = AnthropicModel(model=agent["model"], max_tokens=agent["max_tokens"])
        task, label = args.task or DEMO_TASK, f"Anthropic API ({agent['model']})"
    else:
        model, task, label = MockModel(DEMO_SCRIPT), DEMO_TASK, "mock, scripted"

    print(f"Task: {task}\nModel: {label}\n")
    tools = triage_tools(conn).only(agent["tools"])
    known = {chunk.id for chunk in kb.build_index(conn).chunks}
    try:
        run = run_agent(model, tools, system=agent["system"], task=task, max_turns=agent["max_turns"])
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
    print(f"Finished in {run.turns} turns (limit {agent['max_turns']}).")
    if not report_citations(run.answer, run.transcript, known):
        print("\nStopped: read this draft against its passages before anyone sends it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
