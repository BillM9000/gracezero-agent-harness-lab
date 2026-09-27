"""Ticket rules: who may do what to a ticket, and in which state.

The functions that take a Person (chapter 11) are what the triage assistant's tools call: each
returns only what that person may see (helpdesk/services/access.py), and counts only that too.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from helpdesk.data import repository
from helpdesk.services import access
from helpdesk.services.access import Person
from helpdesk.services.errors import Conflict, Invalid, NotFound

Ticket = dict[str, Any]
Clock = Callable[[], str]

STATUSES = ("open", "pending", "closed")
PRIORITIES = ("low", "normal", "high")
AUTHOR_KINDS = ("customer", "staff", "assistant")

# For find_tickets: which tickets, and how many to a page. Leaving the status out means the ones
# still being worked on.
ACTIVE = ("open", "pending")
STATUS_FILTERS = (*STATUSES, "any")
ASSIGNEES = ("me", "unassigned", "anyone")
PAGE_SIZE = 5
HANDLING_ORDER = {"high": 0, "normal": 1, "low": 2}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create_ticket(
    conn: sqlite3.Connection,
    customer_id: int,
    subject: str,
    body: str,
    priority: str = "normal",
    clock: Clock = utc_now,
) -> Ticket:
    if not subject.strip():
        raise Invalid("subject must not be empty")
    if not body.strip():
        raise Invalid("body must not be empty")
    if priority not in PRIORITIES:
        raise Invalid(f"priority must be one of {', '.join(PRIORITIES)}; got {priority!r}")
    if not repository.customer_exists(conn, customer_id):
        raise Invalid(f"customer {customer_id} does not exist")
    ticket_id = repository.insert_ticket(conn, customer_id, subject.strip(), body.strip(), priority, clock())
    return get_ticket(conn, ticket_id)


def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> Ticket:
    ticket = repository.get_ticket(conn, ticket_id)
    if ticket is None:
        raise NotFound(f"ticket {ticket_id} does not exist")
    ticket["replies"] = repository.list_replies(conn, ticket_id)
    return ticket


def list_tickets(conn: sqlite3.Connection, status: str | None = None) -> list[Ticket]:
    if status is not None and status not in STATUSES:
        raise Invalid(f"status must be one of {', '.join(STATUSES)}; got {status!r}")
    return repository.list_tickets(conn, status)


def add_reply(
    conn: sqlite3.Connection,
    ticket_id: int,
    author_kind: str,
    body: str,
    author_id: int | None = None,
    clock: Clock = utc_now,
) -> Ticket:
    if author_kind not in AUTHOR_KINDS:
        raise Invalid(f"author_kind must be one of {', '.join(AUTHOR_KINDS)}; got {author_kind!r}")
    if not body.strip():
        raise Invalid("reply body must not be empty")
    ticket = get_ticket(conn, ticket_id)
    if ticket["status"] == "closed":
        raise Conflict(f"ticket {ticket_id} is closed; reopen it before replying")
    repository.insert_reply(conn, ticket_id, author_kind, author_id, body.strip(), clock())
    return get_ticket(conn, ticket_id)


def close_ticket(conn: sqlite3.Connection, ticket_id: int, staff_id: int, clock: Clock = utc_now) -> Ticket:
    """Only a member of staff can close a ticket. An assistant can suggest it; a person decides."""
    if not repository.staff_exists(conn, staff_id):
        raise Invalid(f"staff member {staff_id} does not exist; only staff can close tickets")
    ticket = get_ticket(conn, ticket_id)
    if ticket["status"] == "closed":
        raise Conflict(f"ticket {ticket_id} is already closed")
    repository.close_ticket(conn, ticket_id, clock())
    return get_ticket(conn, ticket_id)


# What the assistant's tools call (chapter 11). Every one takes the person the assistant acts for.


@dataclass(frozen=True)
class TicketPage:
    """One page of the tickets a person can see that match a filter."""

    tickets: list[Ticket]
    total: int  # the matching tickets the person can see, on every page
    page: int
    pages: int


def visible_ticket(conn: sqlite3.Connection, person: Person, ticket_id: int) -> Ticket:
    """One ticket and its replies, if the person may see it."""
    ticket = repository.get_ticket(conn, ticket_id)
    if ticket is None or not access.can_see(person, ticket):
        raise NotFound(access.cannot_see(person, ticket_id))
    ticket["replies"] = repository.list_replies(conn, ticket_id)
    return ticket


def ticket_in_context(conn: sqlite3.Connection, person: Person, ticket_id: int) -> Ticket:
    """A ticket as the assistant reads it: names instead of ids, each reply's author, and the
    customer's other tickets that the person may also see."""
    ticket = visible_ticket(conn, person, ticket_id)
    staff = {p.id: p.name for p in access.staff(conn)}
    customers = repository.customer_names(conn)
    ticket["customer_name"] = customers[ticket["customer_id"]]
    ticket["assignee_name"] = staff.get(ticket["assignee_id"])
    for reply in ticket["replies"]:
        kind = reply["author_kind"]
        reply["author_name"] = (
            staff.get(reply["author_id"], "staff")
            if kind == "staff"
            else ticket["customer_name"]
            if kind == "customer"
            else "the assistant"
        )
    ticket["other_tickets"] = [
        other
        for other in repository.list_tickets_for_customer(conn, ticket["customer_id"])
        if other["id"] != ticket_id and access.can_see(person, other)
    ]
    return ticket


def visible_tickets(conn: sqlite3.Connection, person: Person, status: str | None = None) -> list[Ticket]:
    """Every ticket the person may see, in id order, optionally with one status."""
    return [t for t in list_tickets(conn, status) if access.can_see(person, t)]


def find_tickets(
    conn: sqlite3.Connection,
    person: Person,
    status: str | None = None,
    assignee: str = "anyone",
    page: int = 1,
) -> TicketPage:
    """The tickets a person may see that match, in the order to handle them: high priority first,
    oldest first within a priority. PAGE_SIZE to a page. Counts count only what the person may see,
    so a total can't reveal tickets they can't."""
    if status is not None and status not in STATUS_FILTERS:
        raise Invalid(f"status must be one of {', '.join(STATUS_FILTERS)}; got {status!r}")
    if assignee not in ASSIGNEES:
        raise Invalid(f"assignee must be one of {', '.join(ASSIGNEES)}; got {assignee!r}")
    if page < 1:
        raise Invalid(f"page must be 1 or more; got {page}")
    wanted = ACTIVE if status is None else STATUSES if status == "any" else (status,)
    # At lab scale this filters in Python; a large helpdesk puts the same rule in the query.
    rows = [t for t in visible_tickets(conn, person) if t["status"] in wanted]
    if assignee == "me":
        rows = [t for t in rows if t["assignee_id"] == person.id]
    elif assignee == "unassigned":
        rows = [t for t in rows if t["assignee_id"] is None]
    rows.sort(key=lambda t: (HANDLING_ORDER[t["priority"]], t["created_at"], t["id"]))
    pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    if page > pages:
        matching = f"{len(rows)} ticket{'' if len(rows) == 1 else 's'}"
        raise Invalid(
            f"page {page} is past the end: {matching} match, {PAGE_SIZE} to a page, so the last page is "
            f"{pages}."
        )
    staff = {p.id: p.name for p in access.staff(conn)}
    customers = repository.customer_names(conn)
    shown = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    for ticket in shown:
        ticket["customer_name"] = customers[ticket["customer_id"]]
        ticket["assignee_name"] = staff.get(ticket["assignee_id"])
    return TicketPage(shown, len(rows), page, pages)


def customer_for(conn: sqlite3.Connection, person: Person, customer_id: int) -> dict[str, Any]:
    """A customer's name, if the person may see at least one of the customer's tickets."""
    name = repository.customer_names(conn).get(customer_id)
    if name is None or not tickets_for_customer(conn, person, customer_id):
        raise NotFound(f"There is no customer {customer_id} with a ticket {person.name} can see.")
    return {"id": customer_id, "name": name}


def active_by_customer(conn: sqlite3.Connection, person: Person) -> dict[int, list[Ticket]]:
    """The open and pending tickets the person may see, grouped by customer id, each group in
    handling order and the groups in order of their first ticket; each ticket carries its
    customer's name. Grouped by id, because a name isn't unique: two customers called Ada Park are
    two customers. Chapter 14's orchestrator hands out work a customer at a time, and counts what
    came back against this."""
    rows = [t for t in visible_tickets(conn, person) if t["status"] in ACTIVE]
    rows.sort(key=lambda t: (HANDLING_ORDER[t["priority"]], t["created_at"], t["id"]))
    customers = repository.customer_names(conn)
    grouped: dict[int, list[Ticket]] = {}
    for ticket in rows:
        ticket["customer_name"] = customers[ticket["customer_id"]]
        grouped.setdefault(ticket["customer_id"], []).append(ticket)
    return grouped


def tickets_for_customer(conn: sqlite3.Connection, person: Person, customer_id: int) -> list[Ticket]:
    """The customer's tickets that the person may see."""
    rows = repository.list_tickets_for_customer(conn, customer_id)
    return [t for t in rows if access.can_see(person, t)]
