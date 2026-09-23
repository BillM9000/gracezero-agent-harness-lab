"""Ticket rules: who may do what to a ticket, and in which state."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from helpdesk.data import repository
from helpdesk.services.errors import Conflict, Invalid, NotFound

Ticket = dict[str, Any]
Clock = Callable[[], str]

STATUSES = ("open", "pending", "closed")
PRIORITIES = ("low", "normal", "high")
AUTHOR_KINDS = ("customer", "staff", "assistant")


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
