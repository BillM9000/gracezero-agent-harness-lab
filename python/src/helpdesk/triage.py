"""Composition root for the triage assistant's command line.

python -m helpdesk.triage                  the scripted demo, with the mock model
python -m helpdesk.triage --max-turns 2    the same demo, stopped by the turn limit
python -m helpdesk.triage --real "Ticket 3: what should we tell this customer?"
python -m helpdesk.triage --agent FILE     run another agent definition instead of agents/triage.toml
python -m helpdesk.triage --as dana        act for another member of staff (default: sam)
python -m helpdesk.triage --demo propose   chapter 19: the assistant proposes changes for approval
python -m helpdesk.triage --demo redraft   chapter 19: it reads why a draft was rejected, and redrafts
python -m helpdesk.triage --demo injected  chapter 20: a customer's ticket gives it orders, and it obeys
python -m helpdesk.triage --db FILE        work in a saved helpdesk, such as .run/helpdesk.db

The assistant is built from its definition, agents/triage.toml, which must pass the platform's
policy (agents/policy.toml, chapter 18), including its model's retirement date (agents/models.toml,
chapter 20), before anything runs. --real calls Anthropic's API and needs a credential the SDK can
find, such as ANTHROPIC_API_KEY. --demo injected --real would show a real model the injected
ticket. Every --real call is billed, and without --real nothing here calls a model. Each run uses a
fresh in-memory copy of the sample data unless --db names a file, so by default nothing is saved.
The assistant acts for one member of staff, and its tools show only what that person may see
(chapter 11). Its tools that change things only file proposals, which python -m helpdesk.approvals
decides (chapter 19); they need --db to outlast the run. After an answer, every citation in it is
checked against the passages the run's searches returned (chapter 9), and a problem makes the exit
code 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_policy import AGENTS, MODELS, POLICY, load, today
from agent_policy.rules import check
from helpdesk.assistant.agent import TurnLimitReached, run_agent
from helpdesk.assistant.proposing import assistant_tools
from helpdesk.assistant.tools import Toolbox, passages_given
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import is_seeded, seed
from helpdesk.injections import TASK as INJECTED_TASK
from helpdesk.injections import file_case, load_cases, obeying_script
from helpdesk.model.mock import MockModel
from helpdesk.model.stops import IncompleteResponse
from helpdesk.model.types import Message, ModelClient, ModelResponse, ToolCall
from helpdesk.services import access, citations, kb
from helpdesk.services.errors import Invalid

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

# Chapter 19. The mock's drafts are fixed text: it reads nothing, so it can't follow a reason. The
# first draft for ticket 2 promises a refund, which the help article says isn't automatic; the
# redraft is written for the reason in the book's Try it. What the lab proves is that the reason
# reaches the model, in the ticket it reads before drafting again.
PROPOSE_TASK = (
    "Draft replies to tickets 1 and 2 for me to approve. Ticket 3 has been pending since the 3rd; "
    "propose closing it."
)
PROPOSE_SCRIPT = [
    ModelResponse(
        "tool_use",
        tool_calls=(
            ToolCall("call_1", "get_ticket", {"ticket_id": 1}),
            ToolCall("call_2", "get_ticket", {"ticket_id": 2}),
            ToolCall("call_3", "get_ticket", {"ticket_id": 3}),
            ToolCall("call_4", "search_kb", {"query": "downgraded but billed for the old plan"}),
        ),
    ),
    ModelResponse(
        "tool_use",
        tool_calls=(
            ToolCall(
                "call_5",
                "draft_reply",
                {
                    "ticket_id": 2,
                    "reply_text": "Hello Ben, sorry about the confusion. A downgrade takes effect at the "
                    "next billing date, so this invoice was still for Pro, and you kept Pro until then. "
                    "We'll refund the difference to your card today.",
                },
            ),
            ToolCall(
                "call_6",
                "close_ticket",
                {
                    "ticket_id": 3,
                    "reason": "Chloe asked how to export her data, and the help article on exporting "
                    "answers it. The ticket has been pending since 2026-09-03.",
                },
            ),
            ToolCall(
                "call_7",
                "draft_reply",
                {
                    "ticket_id": 1,
                    "reply_text": "Hello Ada, sorry for the trouble. Reset emails can take up to ten minutes "
                    "to arrive, and they sometimes land in the spam folder.",
                },
            ),
        ),
    ),
    ModelResponse(
        "end_turn",
        text=(
            "I filed a reply to Ben on ticket 2 for your approval, and a proposal to close ticket 3, "
            "which needs a lead's approval. I couldn't file a reply on ticket 1: it isn't assigned to "
            "you, so a lead needs to assign it to you first."
        ),
    ),
]
REDRAFT_TASK = "Ticket 2: I sent your reply back. Read why, and file a new one."
REDRAFT_SCRIPT = [
    ModelResponse(
        "tool_use",
        tool_calls=(
            ToolCall("call_1", "get_ticket", {"ticket_id": 2}),
            ToolCall("call_2", "search_kb", {"query": "request a refund"}),
        ),
    ),
    ModelResponse(
        "tool_use",
        tool_calls=(
            ToolCall(
                "call_3",
                "draft_reply",
                {
                    "ticket_id": 2,
                    "reply_text": "Hello Ben, sorry about the confusion. A downgrade takes effect at the "
                    "next billing date, and until then you keep Pro and are billed for it, so this "
                    "invoice is for Pro. Refunds aren't automatic: the account owner can request one "
                    "within 14 days of the charge, under Billing, then History, by choosing Request a "
                    "refund beside it.",
                },
            ),
        ),
    ),
    ModelResponse(
        "end_turn",
        text=(
            "I read why you sent the reply back and filed a new one without the refund promise. It tells "
            "Ben how to request a refund, and it's waiting for your approval."
        ),
    ),
]
DEMOS = {
    "reply": (DEMO_TASK, DEMO_SCRIPT),
    "propose": (PROPOSE_TASK, PROPOSE_SCRIPT),
    "redraft": (REDRAFT_TASK, REDRAFT_SCRIPT),
}


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


def filed_proposals(transcript: tuple[Message, ...], tools: Toolbox) -> int:
    """How many calls to a tool that writes filed a proposal, rather than being refused."""
    writes = {call.id for message in transcript for call in message.tool_calls if call.name in tools.writers}
    return sum(1 for m in transcript for r in m.tool_results if r.call_id in writes and not r.is_error)


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
    parser.add_argument("--as", dest="person", default="sam", help="the member of staff to act for")
    parser.add_argument(
        "--demo", choices=[*DEMOS, "injected"], default="reply", help="which scripted run the mock plays"
    )
    parser.add_argument("--db", help="a helpdesk database file to work in (default: a fresh copy in memory)")
    args = parser.parse_args()
    if args.task and not args.real:
        parser.error("the mock only knows its demo script; add --real to ask your own question")

    # The policy checks what will actually run: the definition, with this run's --max-turns applied.
    agent = load(args.agent)
    if args.max_turns is not None:
        agent["max_turns"] = args.max_turns
    violations = check(agent, load(POLICY), load(MODELS), today())
    if violations:
        for violation in violations:
            print(f"{violation.path}: {violation.reason}", file=sys.stderr)
        refused = "Refused: this agent breaks the platform's policy (agents/policy.toml). Nothing ran."
        print(refused, file=sys.stderr)
        return 2

    if args.db:
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(args.db or ":memory:")
    init_schema(conn)
    if not is_seeded(conn):
        seed(conn)
    # Who the assistant acts for comes from whoever starts it, never from the model (chapter 11).
    try:
        person = access.find_person(conn, args.person)
    except Invalid as e:
        conn.close()
        print(e, file=sys.stderr)
        return 2
    demos = dict(DEMOS)
    if args.demo == "injected":
        # Chapter 20: a customer files a ticket whose text gives the assistant orders, as anyone who
        # can open a ticket could, and the mock plays a model that obeys it (helpdesk/injections.py).
        ticket_id = file_case(conn, load_cases()[0])
        demos["injected"] = (INJECTED_TASK.format(ticket=ticket_id), obeying_script(ticket_id))
    model: ModelClient
    if args.real:
        from helpdesk import gateway  # chapter 27: every real call goes through the one front door

        model = gateway.for_agent(agent)
        task, label = args.task or demos[args.demo][0], f"Anthropic API ({agent['model']})"
    else:
        task, script = demos[args.demo]
        model, label = MockModel(script), "mock, scripted"

    print(f"Task: {task}\nModel: {label}\nActing for: {person.label}\n")
    # The definition's tools, each writer needing the approval its [approval] names (chapter 19).
    tools = assistant_tools(conn, person, agent)
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
    cited = report_citations(run.answer, run.transcript, known)
    if filed_proposals(run.transcript, tools) and not args.db:
        print(
            "\nNothing was saved: this run used a fresh copy of the helpdesk in memory, so its proposals "
            "are gone. Add --db .run/helpdesk.db to keep them for python -m helpdesk.approvals."
        )
    if not cited:
        print("\nStopped: read this draft against its passages before anyone sends it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
