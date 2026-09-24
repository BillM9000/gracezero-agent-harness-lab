"""Composition root for chapter 14's multi-agent patterns. Every run here is the mock, scripted.

python -m helpdesk.patterns revise                  evaluator and optimizer: a draft, the citation
                                                    check's feedback, a revision; at most 3 rounds
python -m helpdesk.patterns revise --max-rounds 1   the same, stopped by the round limit
python -m helpdesk.patterns batch                   orchestrator and workers: every open or pending
                                                    ticket the person can see, a worker a customer,
                                                    and a count of what came back
python -m helpdesk.patterns batch --fail ben        the same, with one customer's worker cut off
python -m helpdesk.patterns compare                 the same batch by one agent two ways and by the
                                                    team, measured

--as chooses the member of staff (default sam); the scripts are written for Sam's tickets. The
orchestrator is built from agents/orchestrator.toml and its workers from agents/triage.toml, and
both must pass the platform's policy (chapter 18) before anything runs. Each run loads the sample
data into a fresh in-memory database, so nothing is saved.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import textwrap
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from agent_policy import AGENTS, POLICY, load
from agent_policy.rules import check
from helpdesk.assistant.agent import AgentRun, run_agent
from helpdesk.assistant.revise import MAX_ROUNDS, Revision, revise
from helpdesk.assistant.team import WORKER_TOOLS, Team, TeamRun, run_team
from helpdesk.assistant.tools import triage_tools
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed
from helpdesk.kb import CHARS_PER_TOKEN
from helpdesk.model.anthropic_client import to_api, tool_to_api
from helpdesk.model.mock import MockCall, MockModel
from helpdesk.model.types import Message, ModelResponse, ToolCall
from helpdesk.services import access, kb
from helpdesk.services.citations import CitationReport
from helpdesk.services.errors import Invalid

# --- The scripts. The mock plays every model's part; the loops, tools and checks are the real code.


def calls(*pairs: tuple[str, dict[str, Any]], turn: str) -> ModelResponse:
    """One turn that calls several tools at once, as a model may when no call needs another's result."""
    return ModelResponse(
        "tool_use",
        tool_calls=tuple(ToolCall(f"{turn}_{i}", name, args) for i, (name, args) in enumerate(pairs, 1)),
    )


REVISE_TASK = "Ticket 1: the customer says the reset email never arrives. Draft a reply."
REVISE_SCRIPT = [
    calls(("get_ticket", {"ticket_id": 1}), ("search_kb", {"query": "reset email never arrives"}), turn="r1"),
    # The first draft changes a fact: the passage says ten minutes.
    ModelResponse(
        "end_turn",
        text=(
            "Hello, and sorry for the trouble. Reset emails can take up to an hour to arrive, and they "
            "sometimes land in the spam folder [1#2]. Check your spam folder, then use the Forgot password "
            "link again [1#2]."
        ),
    ),
    ModelResponse(
        "end_turn",
        text=(
            "Hello, and sorry for the trouble. Reset emails can take up to ten minutes to arrive, and they "
            "sometimes land in the spam folder [1#2]. Check your spam folder, then use the Forgot password "
            "link again [1#2]."
        ),
    ),
]

BATCH_TASK = (
    "Draft a reply to every open or pending ticket I can see, for me to review before anything is sent."
)
BRIEF = "Draft a reply to each of this customer's tickets, for Sam Rivera to review. Cite the help articles."

# Each ticket in the batch: what its worker searches for, and its draft. Every draft uses its
# passages' own words, so the citation check passes it.
TICKETS: dict[int, tuple[str, str]] = {
    1: (
        "reset email never arrives",
        "Ticket 1, Cannot reset my password. Reset emails can take up to ten minutes to arrive, and they "
        "sometimes land in the spam folder [1#2]. Check your spam folder, then use the Forgot password link "
        "again [1#2].",
    ),
    11: (
        "daily summary instead of an email for each change",
        "Ticket 11, Notifications too frequent. By default we send one digest email a day, listing what "
        "changed in your projects [11#1]. Change the time, or switch to a weekly digest, under Settings, "
        "then Notifications [11#1].",
    ),
    12: (
        "API token 401 errors",
        "Ticket 12, API token stopped working. Open Settings, then API, and choose New token [13#1]. Copy "
        "it, and store it somewhere safe: we show a token only once [13#1].",
    ),
    2: (
        "billed for Pro after downgrading",
        "Ticket 2, Invoice shows the wrong plan. Plan changes take effect at the next billing date [2#2]. "
        "Until then you keep the features of your current plan, and you are billed for it [2#2].",
    ),
    6: (
        "invitation link expired",
        "Ticket 6, Invite link expired. An invitation expires after 7 days [6#2]. Open Settings, then "
        "Members, and choose Resend beside their name [6#2]. Resending cancels the old link [6#2].",
    ),
    8: (
        "spreadsheet import stops",
        "Ticket 8, Import stops part way. One file can hold up to 5,000 rows [10#3]. Split a bigger "
        "spreadsheet into several files and import them one after another [10#3].",
    ),
    3: (
        "CSV export of all projects",
        "Ticket 3, How do I export my data? Settings, then Export, produces a CSV of every project you own "
        "[3#1]. Each project becomes one file, and the files arrive together in one zip archive [3#1].",
    ),
    10: (
        "invoice receipt download PDF",
        "Ticket 10, Receipt for August. Every charge has an invoice [9#1]. The owner finds them under "
        "Billing, then History, and can download each one as a PDF [9#1].",
    ),
}
# Sam's batch, a customer at a time in handling order, as tickets.active_by_customer returns it.
CUSTOMERS: dict[str, tuple[int, ...]] = {
    "Ada Park": (1, 11),
    "Ben Okafor": (12, 2),
    "Dev Mistry": (6,),
    "Chloe Varga": (8, 3),
    "Elif Kaya": (10,),
}
IN_ORDER = [ticket for ids in CUSTOMERS.values() for ticket in ids]
LIST_THE_BATCH = (("find_tickets", {}), ("find_tickets", {"page": 2}))


def read_tickets(ids: Iterable[int]) -> list[tuple[str, dict[str, Any]]]:
    ids = list(ids)
    return [("get_ticket", {"ticket_id": i}) for i in ids] + [
        ("search_kb", {"query": TICKETS[i][0]}) for i in ids
    ]


def drafts(ids: Iterable[int]) -> str:
    return "\n\n".join(TICKETS[i][1] for i in ids)


def worker_script(customer: str, *, cut_off: bool = False) -> list[ModelResponse]:
    ids = CUSTOMERS[customer]
    if cut_off:
        # The answer stops at the output limit, part way through: a draft that must not count.
        return [calls(*read_tickets(ids), turn="w1"), ModelResponse("max_tokens", text=drafts(ids)[:60])]
    return [calls(*read_tickets(ids), turn="w1"), ModelResponse("end_turn", text=drafts(ids))]


SUMMARY = (
    "Drafts are ready for all 8 open and pending tickets you can see, from five customers: Ada Park (#1, "
    "#11), Ben Okafor (#12, #2), Dev Mistry (#6), Chloe Varga (#8, #3) and Elif Kaya (#10). Every report "
    "says the citations hold. Start with #1 and #12, the two high-priority tickets."
)
ORCHESTRATOR_SCRIPT = [
    calls(*LIST_THE_BATCH, turn="o1"),
    calls(*[("delegate_customer", {"customer_name": c, "brief": BRIEF}) for c in CUSTOMERS], turn="o2"),
    # The script doesn't change when a worker fails. The count at the end doesn't depend on it.
    ModelResponse("end_turn", text=SUMMARY),
]

# The same batch by one agent with the triage assistant's tools, in one context.
ALL_AT_ONCE = [
    calls(*LIST_THE_BATCH, turn="a1"),
    calls(*read_tickets(IN_ORDER), turn="a2"),
    ModelResponse("end_turn", text=drafts(IN_ORDER)),
]
TICKET_BY_TICKET = [
    calls(*LIST_THE_BATCH, turn="t1"),
    *[calls(*read_tickets([i]), turn=f"t{n}") for n, i in enumerate(IN_ORDER, 2)],
    ModelResponse("end_turn", text=drafts(IN_ORDER)),
]


# --- Building and checking the agents.


def definitions() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """The orchestrator's and the workers' definitions, and every way either breaks the policy."""
    policy = load(POLICY)
    orchestrator, worker = load(AGENTS / "orchestrator.toml"), load(AGENTS / "triage.toml")
    found = [
        f"{name}.toml: {v.path}: {v.reason}"
        for name, d in (("orchestrator", orchestrator), ("triage", worker))
        for v in check(d, policy)
    ]
    missing = [t for t in WORKER_TOOLS if t not in worker["tools"]]
    if missing:
        found.append(
            f"triage.toml: tools: a worker needs {', '.join(missing)}, and the definition doesn't allow it."
        )
    return orchestrator, worker, found


def known_passages(conn: sqlite3.Connection) -> set[str]:
    return {chunk.id for chunk in kb.build_index(conn).chunks}


def build_team(
    conn: sqlite3.Connection,
    person: access.Person,
    worker: dict[str, Any],
    models: Callable[[str], MockModel],
) -> Team:
    return Team(
        conn,
        person,
        models,
        system=worker["system"],
        known=known_passages(conn),
        max_turns=worker["max_turns"],
    )


def scripted_workers(fail: str | None = None) -> tuple[Callable[[str], MockModel], dict[str, MockModel]]:
    """A mock for each worker, made when the worker starts, and a record of them for measuring."""
    made: dict[str, MockModel] = {}

    def model_for(customer: str) -> MockModel:
        cut = fail is not None and customer.lower().startswith(fail.lower())
        made[customer] = MockModel(worker_script(customer, cut_off=cut))
        return made[customer]

    return model_for, made


# --- Measuring what each design sends.


def request_size(call: MockCall, *, with_messages: bool = True) -> int:
    """Characters of one request as the Anthropic adapter would send it; without its messages, the
    part every request of that context repeats: the system prompt and the tool definitions."""
    request = {
        "system": call.system,
        "tools": [tool_to_api(t) for t in call.tools],
        "messages": [to_api(m) for m in call.messages] if with_messages else [],
    }
    return len(json.dumps(request, ensure_ascii=False))


def request_sizes(calls_made: Iterable[MockCall]) -> list[int]:
    return [request_size(call) for call in calls_made]


@dataclass(frozen=True)
class Context:
    """One conversation with the model, and what each of its requests sent."""

    name: str
    requests: tuple[int, ...]  # characters of each request
    fixed: int  # characters of the system prompt and tool definitions, repeated in every request
    transcript: tuple[Message, ...]


def context(name: str, model: MockModel, transcript: tuple[Message, ...]) -> Context:
    fixed = request_size(model.calls[0], with_messages=False)
    return Context(name, tuple(request_sizes(model.calls)), fixed, transcript)


@dataclass(frozen=True)
class Measured:
    contexts: tuple[Context, ...]
    answer: str  # every draft, in batch order

    @property
    def requests(self) -> int:
        return sum(len(c.requests) for c in self.contexts)

    @property
    def largest(self) -> int:
        return max(size for c in self.contexts for size in c.requests)

    @property
    def sent(self) -> int:
        return sum(sum(c.requests) for c in self.contexts)


# The three designs, as the comparison's table heads them.
DESIGNS = (
    ("one agent,", "all at once"),
    ("one agent,", "a ticket at a time"),
    ("orchestrator and", "5 workers"),
)


def compare(conn: sqlite3.Connection, person: access.Person) -> dict[tuple[str, str], Measured]:
    orchestrator, worker, _ = definitions()
    tools = triage_tools(conn, person).only(worker["tools"])
    results: dict[tuple[str, str], Measured] = {}
    for design, script in zip(DESIGNS[:2], (ALL_AT_ONCE, TICKET_BY_TICKET), strict=True):
        model = MockModel(script)
        run = run_agent(model, tools, system=worker["system"], task=BATCH_TASK, max_turns=len(script))
        results[design] = Measured((context("one agent", model, run.transcript),), run.answer)
    lead = MockModel(ORCHESTRATOR_SCRIPT)
    models, made = scripted_workers()
    team = build_team(conn, person, worker, models)
    team_run = run_team(lead, team, system=orchestrator["system"], task=BATCH_TASK)
    if team_run.orchestrator is None:
        raise RuntimeError(f"The scripted orchestrator stopped: {team_run.stopped}")
    contexts = [context("orchestrator", lead, team_run.orchestrator.transcript)]
    contexts += [context(w.customer, made[w.customer], w.run.transcript) for w in team_run.workers if w.run]
    answer = "\n\n".join(w.run.answer for w in team_run.workers if w.run)
    results[DESIGNS[2]] = Measured(tuple(contexts), answer)
    return results


# --- Printing.


def indented(text: str, prefix: str = "  ") -> str:
    return "\n".join(
        textwrap.fill(paragraph, 100, initial_indent=prefix, subsequent_indent=prefix) if paragraph else ""
        for paragraph in text.split("\n")
    )


def print_check(draft_report: CitationReport) -> None:
    if draft_report.ok:
        given = "against the passages this conversation was given"
        print(f"Check: {draft_report.checked} citations checked {given}; all hold.")
        return
    print(f"Check: {len(draft_report.problems)} problem(s)")
    for problem in draft_report.problems:
        print(f"  {problem.reason}\n    in: {problem.sentence}")


def run_revise(
    conn: sqlite3.Connection, person: access.Person, worker: dict[str, Any], max_rounds: int
) -> int:
    print(f"Task: {REVISE_TASK}\nModel: mock, scripted\nActing for: {person.label}\n")
    model = MockModel(REVISE_SCRIPT)
    tools = triage_tools(conn, person).only(WORKER_TOOLS)
    result: Revision = revise(
        model,
        tools,
        system=worker["system"],
        task=REVISE_TASK,
        known=known_passages(conn),
        max_rounds=max_rounds,
    )
    for draft in result.drafts:
        print(f"Round {draft.round}, draft:\n{indented(draft.answer)}")
        print_check(draft.report)
        if draft is not result.drafts[-1]:
            print("Sent back to the drafter with the check's findings.")
        print()
    sizes = request_sizes(model.calls)
    cost = f"{len(sizes)} requests to the model, {sum(sizes):,} characters sent."
    rounds = f"{len(result.drafts)} round{'s' if len(result.drafts) > 1 else ''} (limit {max_rounds})"
    if result.accepted:
        print(f"Accepted after {rounds}. {cost}")
        return 0
    why = {
        "limit": "the draft still fails the check",
        "unchanged": "the draft came back unchanged, so another round wouldn't help",
    }[result.stopped]
    print(f"Stopped after {rounds}: {why}. {cost}")
    print("A person reads this draft, and its problems, before anything is sent.")
    return 1


def run_batch(
    conn: sqlite3.Connection,
    person: access.Person,
    orchestrator: dict[str, Any],
    worker: dict[str, Any],
    fail: str | None,
) -> int:
    print(f"Task: {BATCH_TASK}\nModel: mock, scripted\nActing for: {person.label}\n")
    models, _ = scripted_workers(fail)
    team = build_team(conn, person, worker, models)
    result: TeamRun = run_team(
        MockModel(ORCHESTRATOR_SCRIPT),
        team,
        system=orchestrator["system"],
        task=BATCH_TASK,
        max_turns=orchestrator["max_turns"],
    )
    if result.orchestrator is None:
        print(f"The orchestrator stopped without a summary: {result.stopped}")
    else:
        print_orchestrator(result.orchestrator)
    print("\nDrafts filed for the person, one worker's at a time:")
    for w in result.workers:
        if w.run:
            print(f"\n{w.customer}, from a worker with its own context ({w.run.turns} turns):")
            print(indented(w.run.answer))
    print("\nCounted in code, not taken from the summary:")
    for line in result.accounting.lines():
        print(f"  {line}")
    if result.accounting.complete and result.orchestrator is not None:
        return 0
    print("\nStopped: the batch isn't complete, whatever the summary says. Read what's missing above.")
    return 1


def print_orchestrator(run: AgentRun) -> None:
    turn = 0
    for message in run.transcript[1:]:
        if message.role == "assistant":
            turn += 1
            for call in message.tool_calls:
                line = f"turn {turn}  calls {call.name} {json.dumps(call.arguments)}"
                print(textwrap.fill(line, 100, subsequent_indent=" " * 14))
        for result in message.tool_results:
            if result.content.startswith("Tickets "):
                # A page of tickets: its first line here, to keep the transcript short.
                first, *rest = result.content.splitlines()
                print(f"        result: {first} [{len(rest)} more lines]")
                continue
            label = "error" if result.is_error else "result"
            print(
                textwrap.fill(
                    result.content, 100, initial_indent=f"        {label}: ", subsequent_indent=" " * 16
                )
            )
    print(f"turn {run.turns}  answers:\n{indented(run.answer)}")


def run_compare(conn: sqlite3.Connection, person: access.Person) -> int:
    results = compare(conn, person)
    batch = f"{len(IN_ORDER)} tickets from {len(CUSTOMERS)} customers"
    print(
        paragraph(
            f"The same batch, {batch}, drafted three ways by the mock, acting for {person.label}. "
            "Characters are counted as the Anthropic adapter would send them; tokens are estimated at "
            f"{CHARS_PER_TOKEN} characters each."
        )
        + "\n"
    )
    width = 34
    for line in range(2):
        print(" " * width + "".join(f"{design[line]:>20}" for design in DESIGNS))
    rows = [
        ("separate contexts", lambda m: f"{len(m.contexts)}"),
        ("requests to the model", lambda m: f"{m.requests}"),
        ("largest request, characters", lambda m: f"{m.largest:,}"),
        ("sent to the model, characters", lambda m: f"{m.sent:,}"),
        ("sent to the model, tokens (est.)", lambda m: f"{round(m.sent / CHARS_PER_TOKEN):,}"),
    ]
    for label, show in rows:
        print(f"{label:<{width}}" + "".join(f"{show(results[d]):>20}" for d in DESIGNS))
    lead, *workers = results[DESIGNS[2]].contexts
    single = results[DESIGNS[0]].contexts[0]
    requests = sum(len(w.requests) for w in workers)
    lead_sent, workers_sent = sum(lead.requests), sum(sum(w.requests) for w in workers)
    print(
        "\n"
        + paragraph(
            f"In the team, the orchestrator's {len(lead.requests)} requests sent {lead_sent:,} characters "
            f"and the workers' {requests} sent {workers_sent:,}. Every request repeats its system prompt "
            f"and tool definitions: {workers[0].fixed:,} characters for a worker, {lead.fixed:,} for the "
            f"orchestrator and {single.fixed:,} for the one agent."
        )
    )
    print(
        "\n"
        + paragraph(
            "Each column is the path its script takes: the fewest turns for the first and third, and one "
            "ticket a turn for the second. A real model takes its own path; measure that on a golden set "
            "(chapter 21). Output tokens aren't counted here, and every design writes the same drafts."
        )
    )
    return 0


def paragraph(text: str) -> str:
    return textwrap.fill(text, 100)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.patterns")
    sub = parser.add_subparsers(dest="command", required=True)
    revise_command = sub.add_parser("revise", help="evaluator and optimizer")
    revise_command.add_argument(
        "--max-rounds", type=int, default=MAX_ROUNDS, help=f"drafts to check (default {MAX_ROUNDS})"
    )
    batch_command = sub.add_parser("batch", help="orchestrator and workers")
    batch_command.add_argument(
        "--fail", metavar="NAME", help="cut off the worker for this customer's first name"
    )
    sub.add_parser("compare", help="one agent against the team, measured")
    for command in sub.choices.values():
        command.add_argument("--as", dest="person", default="sam", help="the member of staff to act for")
    args = parser.parse_args()

    orchestrator, worker, violations = definitions()
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(
            "Refused: an agent here breaks the platform's policy (agents/policy.toml). Nothing ran.",
            file=sys.stderr,
        )
        return 2
    if args.command == "revise" and args.max_rounds < 1:
        parser.error("--max-rounds must be 1 or more")

    conn = connect(":memory:")
    try:
        init_schema(conn)
        seed(conn)
        try:
            person = access.find_person(conn, args.person)
        except Invalid as e:
            print(e, file=sys.stderr)
            return 2
        if args.command == "revise":
            return run_revise(conn, person, worker, args.max_rounds)
        if args.command == "batch":
            return run_batch(conn, person, orchestrator, worker, args.fail)
        return run_compare(conn, person)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
