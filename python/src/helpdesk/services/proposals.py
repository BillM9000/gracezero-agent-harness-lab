"""The approval queue as an agent's tools see it (chapter 19): file a proposal, nothing more.

An agent never changes a ticket. Its tools that write call propose(), which checks what the person
the agent acts for may change (helpdesk/services/access.py), files the change for a member of staff
to approve, and records the step in the approval log. A refusal is recorded too. Deciding a proposal
is helpdesk/services/decisions.py, which only the approval command may import (a contract in
pyproject.toml), so nothing an agent can call approves anything.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

from helpdesk.data import repository
from helpdesk.services import access
from helpdesk.services.access import Person
from helpdesk.services.errors import Conflict, Forbidden, Invalid, NotFound, ServiceError
from helpdesk.services.tickets import Clock, utc_now
from helpdesk.services.untrusted import Flag

# What each kind of proposal does once approved, in words.
KINDS = {"reply": "send a reply", "close": "close the ticket"}


def propose(
    conn: sqlite3.Connection,
    person: Person,
    agent: str,
    kind: str,
    ticket_id: int,
    text: str,
    needs: str,
    clock: Clock = utc_now,
    flags: Sequence[Flag] = (),
) -> dict[str, Any]:
    """File a change for approval, for the person the agent acts for. Refuses, and records the
    refusal, when that person may not change the ticket, when the ticket is closed, or when the same
    kind of change is already waiting on it. flags are what the agent had read that looked like
    instructions (chapter 20); they go with the proposal to whoever decides it, and change nothing
    about whether it may be filed."""
    if kind not in KINDS:
        raise Invalid(f"kind must be one of {', '.join(KINDS)}; got {kind!r}")
    if needs not in access.APPROVERS:
        # The tool was built without a known approval. Fail closed: file nothing.
        raise Invalid(f"needs must be one of {', '.join(access.APPROVERS)}; got {needs!r}")
    if not text.strip():
        raise Invalid("the text must not be empty")
    now = clock()
    ticket = repository.get_ticket(conn, ticket_id)
    waiting = [
        p
        for p in repository.list_proposals_for_ticket(conn, ticket_id)
        if p["kind"] == kind and p["status"] == "pending"
    ]
    problem: ServiceError | None = None
    if ticket is None or not access.can_see(person, ticket):
        problem = NotFound(access.cannot_see(person, ticket_id))
    elif not access.can_change(person, ticket):
        problem = Forbidden(access.cannot_change(person, ticket))
    elif ticket["status"] == "closed":
        problem = Conflict(f"Ticket {ticket_id} is closed, so nothing was filed. Tell {person.first_name}.")
    elif waiting:
        problem = Conflict(
            f"Proposal #{waiting[0]['id']} to {KINDS[kind]} on ticket {ticket_id} is still waiting for "
            "approval, so nothing new was filed. Wait for its decision."
        )
    if problem is not None:
        repository.insert_log(
            conn, now, "refused", person.id, f"{KINDS[kind]}: {problem}", ticket_id=ticket_id, agent=agent
        )
        conn.commit()
        raise problem
    proposal_id = repository.insert_proposal(
        conn, kind, ticket_id, text.strip(), agent, person.id, needs, now
    )
    for flag in flags:
        repository.insert_proposal_flag(conn, proposal_id, flag.source, flag.phrase)
    repository.insert_log(
        conn,
        now,
        "proposed",
        person.id,
        text.strip(),
        proposal_id=proposal_id,
        ticket_id=ticket_id,
        agent=agent,
    )
    conn.commit()
    return get(conn, person, proposal_id)


def get(conn: sqlite3.Connection, person: Person, proposal_id: int) -> dict[str, Any]:
    """One proposal, if the person may see its ticket, with the names of who it was for and who
    decided it. A proposal on a ticket the person can't see gets the same answer as a missing one."""
    proposal = repository.get_proposal(conn, proposal_id)
    ticket = repository.get_ticket(conn, proposal["ticket_id"]) if proposal else None
    if proposal is None or ticket is None or not access.can_see(person, ticket):
        raise NotFound(f"There is no proposal #{proposal_id} that {person.name} can see.")
    return named(conn, proposal)


def named(conn: sqlite3.Connection, proposal: dict[str, Any]) -> dict[str, Any]:
    """A proposal with names instead of ids: its ticket's subject, who it was for and who decided
    it, and the flags filed with it (chapter 20)."""
    staff = {p.id: p.name for p in access.staff(conn)}
    ticket = repository.get_ticket(conn, proposal["ticket_id"])
    return {
        **proposal,
        "subject": ticket["subject"] if ticket else None,
        "proposed_for_name": staff.get(proposal["proposed_for"]),
        "decided_by_name": staff.get(proposal["decided_by"]),
        "flags": repository.list_proposal_flags(conn, proposal["id"]),
    }
