"""Orchestrator and workers (chapter 14).

The orchestrator is an agent like any other, with one tool the triage assistant doesn't have:
delegate_customer, which starts a worker. A worker is a fresh agent with its own context: no
history, the triage assistant's two reading tools, and a brief from the orchestrator. When it
finishes, its drafts are checked (chapter 9's citation check, against what that worker was given)
and filed for the person the team works for, and the orchestrator gets back a short report instead
of the worker's transcript.

Three rules, each kept in code rather than asked of a model:
- The unit of work is a customer. Everything one customer has open is decided in one context, so
  two workers can't tell the same customer different things; a customer is delegated once.
- Workers can't delegate. They get get_ticket and search_kb, and nothing else.
- The team's result is counted here, not taken from the orchestrator's summary: every customer in
  the batch has a worker whose drafts passed the check, or the run is incomplete and says which
  customers and tickets are missing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field

from helpdesk.assistant.agent import AgentRun, TurnLimitReached, run_agent
from helpdesk.assistant.tools import Tool, Toolbox, passages_given, triage_tools
from helpdesk.model.stops import IncompleteResponse
from helpdesk.model.types import Message, ModelClient, ToolSpec
from helpdesk.services import citations, tickets
from helpdesk.services.access import Person
from helpdesk.services.citations import CitationReport
from helpdesk.services.errors import Conflict, NotFound, ServiceError

# What a worker may use: reading only, and no delegate_customer, so a worker can't start workers.
WORKER_TOOLS = ("get_ticket", "search_kb")

DELEGATE = ToolSpec(
    "delegate_customer",
    "Hand every open or pending ticket of one customer to a worker: a separate assistant with its own "
    "context, which reads each ticket, searches the help articles and drafts a reply to each. The "
    "worker sees only your brief and its own tool results, never this conversation or other workers' "
    "work, so say in the brief everything it needs. Returns a short report of what was drafted and "
    "whether the drafts' citations hold up; the drafts themselves go to the person you work for. "
    "Delegate each customer once. To find the customers, use find_tickets.",
    {
        "type": "object",
        "properties": {
            "customer_name": {
                "type": "string",
                "minLength": 1,
                "description": "The customer's full name as find_tickets shows it, such as Ben Okafor.",
            },
            "brief": {
                "type": "string",
                "minLength": 1,
                "description": "What the worker should do, in a sentence or two.",
            },
        },
        "required": ["customer_name", "brief"],
        "additionalProperties": False,
    },
    strict=True,
)


class WorkerFailed(ServiceError):
    """A worker ended without drafts. The message says what the orchestrator should do."""


@dataclass(frozen=True)
class Worker:
    """One worker's run, kept outside the orchestrator's context for the person and the count."""

    customer: str
    ticket_ids: tuple[int, ...]
    run: AgentRun | None
    report: CitationReport | None
    error: str | None = None

    @property
    def unread(self) -> tuple[int, ...]:
        """Tickets handed to this worker that its transcript never shows it reading."""
        read = tickets_read(self.run.transcript) if self.run else set()
        return tuple(i for i in self.ticket_ids if i not in read)

    @property
    def ok(self) -> bool:
        return self.run is not None and self.report is not None and self.report.ok and not self.unread

    def why_not(self) -> str:
        if self.error:
            return self.error
        if self.unread:
            return (
                f"its worker never read {numbers(self.unread)}, so a draft for it can't rest on the ticket."
            )
        count = len(self.report.problems) if self.report else 0
        return f"{count} citation problem(s); a person must read the drafts before anything is sent."


def tickets_read(transcript: Iterable[Message]) -> set[int]:
    """The tickets a run's get_ticket calls returned, from the transcript: what the worker really read."""
    messages = list(transcript)
    asked = {
        call.id: call.arguments.get("ticket_id")
        for message in messages
        for call in message.tool_calls
        if call.name == "get_ticket"
    }
    return {
        asked[result.call_id]
        for message in messages
        for result in message.tool_results
        if result.call_id in asked and not result.is_error
    }


@dataclass(frozen=True)
class Accounting:
    """What came back, counted against the batch the service says there is."""

    batch: dict[str, tuple[int, ...]]  # customer: ticket ids, from the tickets service
    drafted: tuple[str, ...]  # customers whose worker's drafts passed the check
    failed: dict[str, str]  # customer: why there are no usable drafts
    missing: tuple[str, ...]  # customers never delegated

    @property
    def complete(self) -> bool:
        return not self.failed and not self.missing

    def lines(self) -> list[str]:
        tickets_in = sum(len(ids) for ids in self.batch.values())
        tickets_done = sum(len(self.batch[c]) for c in self.drafted)
        head = (
            f"{len(self.drafted)} of {len(self.batch)} customers, {tickets_done} of {tickets_in} tickets, "
            "have drafts whose citations hold."
        )
        out = [head]
        for customer, why in self.failed.items():
            out.append(f"No usable drafts for {customer} ({numbers(self.batch[customer])}): {why}")
        for customer in self.missing:
            out.append(f"Never delegated: {customer} ({numbers(self.batch[customer])}).")
        return out


def numbers(ids: Collection[int]) -> str:
    return ", ".join(f"#{i}" for i in ids)


@dataclass
class Team:
    """The workers one orchestrator run starts, for one member of staff."""

    conn: sqlite3.Connection
    person: Person
    worker_model: Callable[[str], ModelClient]  # a model for the worker on this customer
    system: str  # the workers' system prompt
    known: Collection[str]  # every passage id in the knowledge base
    max_turns: int = 6
    workers: dict[str, Worker] = field(default_factory=dict)

    def batch(self) -> dict[str, tuple[int, ...]]:
        by_customer = tickets.active_by_customer(self.conn, self.person)
        return {customer: tuple(t["id"] for t in rows) for customer, rows in by_customer.items()}

    def delegate(self, customer_name: str, brief: str) -> str:
        batch = self.batch()
        if customer_name not in batch:
            raise NotFound(
                f"No open or pending tickets that {self.person.name} can see are from a customer called "
                f"{customer_name!r}. Use the name exactly as find_tickets shows it."
            )
        if customer_name in self.workers:
            raise Conflict(
                f"{customer_name} was already delegated. One worker handles every ticket of one "
                "customer, so nothing is decided twice; read the report you already have."
            )
        ids = batch[customer_name]
        toolbox = triage_tools(self.conn, self.person).only(WORKER_TOOLS)
        task = f"{brief}\nThe tickets: {numbers(ids)}, all from {customer_name}."
        try:
            run = run_agent(
                self.worker_model(customer_name),
                toolbox,
                system=self.system,
                task=task,
                max_turns=self.max_turns,
            )
        except (TurnLimitReached, IncompleteResponse) as stop:
            self.workers[customer_name] = Worker(customer_name, ids, None, None, str(stop))
            raise WorkerFailed(
                f"The worker for {customer_name} stopped without drafts: {stop} Tickets {numbers(ids)} "
                "have no draft. Tell the person so, and don't count them as done."
            ) from None
        report = citations.check(run.answer, passages_given(run.transcript), self.known)
        worker = Worker(customer_name, ids, run, report)
        self.workers[customer_name] = worker
        checked = (
            f"all {report.checked} citations hold." if worker.ok else f"not usable yet: {worker.why_not()}"
        )
        return (
            f"{customer_name}: drafts for {numbers(ids)}, written in {run.turns} turns; {checked} "
            f"The drafts are filed for {self.person.name}."
        )

    def tool(self) -> Tool:
        return Tool(DELEGATE, self.delegate)

    def account(self) -> Accounting:
        batch = self.batch()
        drafted = tuple(c for c in batch if c in self.workers and self.workers[c].ok)
        failed = {customer: worker.why_not() for customer, worker in self.workers.items() if not worker.ok}
        missing = tuple(c for c in batch if c not in self.workers)
        return Accounting(batch, drafted, failed, missing)


def orchestrator_tools(team: Team) -> Toolbox:
    """The orchestrator's tools: find_tickets to see the work, and delegate_customer to hand it out."""
    return triage_tools(team.conn, team.person).only(["find_tickets"]).plus(team.tool())


@dataclass(frozen=True)
class TeamRun:
    orchestrator: AgentRun | None  # None when the orchestrator itself stopped without an answer
    workers: tuple[Worker, ...]
    accounting: Accounting
    stopped: str | None = None  # why the orchestrator stopped, when it did


def run_team(model: ModelClient, team: Team, *, system: str, task: str, max_turns: int = 6) -> TeamRun:
    """Run the orchestrator, then count what its workers brought back. The count never depends on
    what the orchestrator's answer says, and it's made even when the orchestrator stops part way."""
    try:
        run = run_agent(model, orchestrator_tools(team), system=system, task=task, max_turns=max_turns)
    except (TurnLimitReached, IncompleteResponse) as stop:
        return TeamRun(None, tuple(team.workers.values()), team.account(), str(stop))
    return TeamRun(run, tuple(team.workers.values()), team.account())
