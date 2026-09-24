"""Deciding a proposal (chapter 19): approve it and the change happens; reject it with a reason.

Only the approval command, python -m helpdesk.approvals, may import this module (a contract in
pyproject.toml), so no tool an agent can call reaches it. Every function takes the person deciding,
who comes from whoever runs the command, never from an agent.

- approve checks again, at the moment of deciding, everything the change depends on: that the person
  may give the approval it needs, that it's still pending, and that the ticket can still take it.
  The decision, the change and its record in the approval log commit together, or not at all.
- reject needs a reason. It's what the assistant reads the next time it looks at the ticket.
- Refusals are recorded too.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from helpdesk.data import repository
from helpdesk.services import access
from helpdesk.services.access import NEEDS, Person
from helpdesk.services.errors import Conflict, Forbidden, Invalid, NotFound
from helpdesk.services.proposals import get
from helpdesk.services.tickets import Clock, utc_now


@dataclass(frozen=True)
class Queue:
    """The pending proposals a person may see: those they may decide, and those waiting for someone
    else, such as a lead."""

    theirs: list[dict[str, Any]]
    others: list[dict[str, Any]]


def queue(conn: sqlite3.Connection, person: Person) -> Queue:
    theirs, others = [], []
    for proposal in repository.list_proposals(conn, "pending"):
        ticket = repository.get_ticket(conn, proposal["ticket_id"])
        if ticket is None or not access.can_see(person, ticket):
            continue
        mine = access.may_approve(person, proposal["needs"], ticket)
        (theirs if mine else others).append(get(conn, person, proposal["id"]))
    return Queue(theirs, others)


def recipient(conn: sqlite3.Connection, person: Person, proposal_id: int) -> str:
    """Who a proposed reply goes to, email address included, for a person who may decide it and no
    one else. Chapter 15's fitness test keeps customers' addresses out of every read route; this is
    the one place that shows one, and it checks who is asking first."""
    proposal = get(conn, person, proposal_id)
    ticket = repository.get_ticket(conn, proposal["ticket_id"])
    if not access.may_approve(person, proposal["needs"], ticket):
        raise Forbidden(f"Only someone who may decide #{proposal_id} sees where it goes.")
    name = repository.customer_names(conn)[ticket["customer_id"]]
    return f"{name} <{repository.customer_email(conn, ticket['customer_id'])}>"


def _decidable(
    conn: sqlite3.Connection, person: Person, proposal_id: int, verb: str, now: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The proposal and its ticket, if this person may decide it now. Otherwise the refusal is
    recorded and raised."""
    try:
        proposal = get(conn, person, proposal_id)
    except NotFound as missing:
        # No proposal id in the record: it may not exist, and the log only points at real ones.
        repository.insert_log(conn, now, "refused", person.id, f"{verb} #{proposal_id}: {missing}")
        conn.commit()
        raise
    ticket = repository.get_ticket(conn, proposal["ticket_id"])
    problem: Forbidden | Conflict | None = None
    if proposal["status"] != "pending":
        problem = Conflict(f"#{proposal_id} was already {proposal['status']}, so nothing changed.")
    elif not access.may_approve(person, proposal["needs"], ticket):
        problem = Forbidden(
            f"#{proposal_id} needs the approval of {NEEDS[proposal['needs']]}, and {person.name} is "
            f"{person.role}, so {person.first_name} can't {verb} it. Nothing changed."
        )
    elif proposal["kind"] == "reply" and ticket["status"] == "closed":
        problem = Conflict(
            f"Ticket {ticket['id']} was closed after #{proposal_id} was filed, so the reply can't be sent. "
            "Nothing changed; reject it with that reason."
        )
    elif proposal["kind"] == "close" and ticket["status"] == "closed":
        problem = Conflict(
            f"Ticket {ticket['id']} is already closed. Nothing changed; reject #{proposal_id}."
        )
    if problem is not None:
        detail = f"{verb}: {problem}"
        repository.insert_log(conn, now, "refused", person.id, detail, proposal_id, ticket["id"])
        conn.commit()
        raise problem
    return proposal, ticket


def approve(conn: sqlite3.Connection, person: Person, proposal_id: int, clock: Clock = utc_now) -> str:
    """Approve a proposal, and make the change it proposed. Returns what happened, in words."""
    now = clock()
    proposal, ticket = _decidable(conn, person, proposal_id, "approve", now)
    try:
        if not repository.decide_proposal(conn, proposal_id, "approved", person.id, None, now):
            raise Conflict(f"#{proposal_id} was decided by someone else a moment ago. Nothing changed.")
        if proposal["kind"] == "reply":
            # Sent in the approver's name: whoever approves a reply answers for it.
            repository.insert_reply(
                conn, ticket["id"], "staff", person.id, proposal["text"], now, commit=False
            )
            done = f"the reply is on ticket {ticket['id']}, from {person.name}"
        else:
            repository.close_ticket(conn, ticket["id"], now, commit=False)
            done = f"ticket {ticket['id']} is closed"
        repository.insert_log(conn, now, "approved", person.id, done, proposal_id, ticket["id"])
        conn.commit()
    except Exception:
        # The decision, the change and the record go together. If any part fails, none of it stays.
        conn.rollback()
        raise
    return done


def reject(
    conn: sqlite3.Connection, person: Person, proposal_id: int, reason: str, clock: Clock = utc_now
) -> None:
    """Reject a proposal. The reason is required: it's the feedback the assistant reads."""
    if not reason.strip():
        raise Invalid(
            "Give a reason with --reason. It's what the assistant reads the next time it looks at the "
            "ticket, so say what to change."
        )
    now = clock()
    proposal, ticket = _decidable(conn, person, proposal_id, "reject", now)
    if not repository.decide_proposal(conn, proposal_id, "rejected", person.id, reason.strip(), now):
        raise Conflict(f"#{proposal_id} was decided by someone else a moment ago. Nothing changed.")
    repository.insert_log(conn, now, "rejected", person.id, reason.strip(), proposal_id, ticket["id"])
    conn.commit()


def log(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every step in the approval log, oldest first, with the person's name."""
    staff = {p.id: p.name for p in access.staff(conn)}
    return [{**row, "staff_name": staff.get(row["staff_id"], "?")} for row in repository.list_log(conn)]
