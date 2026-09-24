"""Who the triage assistant works for, and what that person may see (chapter 11).

The assistant always acts for one member of staff, chosen by whoever starts it: in a real app, the
person who is signed in; here, python -m helpdesk.triage --as. The tools are built for that person
and check every ticket against them, in code, on every call. No tool takes the person as an
argument, so nothing the model writes can change whose permissions it uses.

The rule: a lead sees every ticket; support staff see the tickets assigned to them and the
unassigned queue. Chapter 19 extends it to writes, for the tools that propose a change: a lead may
change any ticket, support staff only their own. That answers "may this person do it at all?"
before anyone is asked to approve it; may_approve answers "may this person approve it?".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from helpdesk.data import repository
from helpdesk.services.errors import Invalid

# What each role may see, in words, for messages. can_see below is the rule itself.
RULES = {
    "lead": "a lead sees every ticket",
    "support": "support staff see the tickets assigned to them and unassigned ones",
}


@dataclass(frozen=True)
class Person:
    """A member of staff the assistant acts for."""

    id: int
    name: str
    role: str  # "support" or "lead", as the staff table allows

    @property
    def first_name(self) -> str:
        return self.name.split()[0]

    @property
    def label(self) -> str:
        return f"{self.name} ({self.role})"


def staff(conn: sqlite3.Connection) -> list[Person]:
    return [Person(row["id"], row["name"], row["role"]) for row in repository.list_staff(conn)]


def find_person(conn: sqlite3.Connection, who: str) -> Person:
    """A member of staff by id or by first name, in any case: "1", "sam" or "Sam"."""
    everyone = staff(conn)
    for person in everyone:
        if who.strip().lower() in (str(person.id), person.first_name.lower()):
            return person
    known = ", ".join(f"{p.first_name.lower()} ({p.name}, {p.role})" for p in everyone)
    raise Invalid(f"No member of staff called {who!r}. Choose one of: {known}.")


def can_see(person: Person, ticket: dict[str, Any]) -> bool:
    """The rule every tool applies to every ticket it reads, lists or counts."""
    if person.role == "lead":
        return True
    if person.role == "support":
        return ticket["assignee_id"] in (None, person.id)
    return False  # a role this rule doesn't know sees nothing: it fails closed


def can_change(person: Person, ticket: dict[str, Any]) -> bool:
    """The rule for writes (chapter 19), stricter than can_see: support staff see the unassigned
    queue, but change only the tickets assigned to them."""
    if person.role == "lead":
        return True
    if person.role == "support":
        return ticket["assignee_id"] == person.id
    return False  # fails closed, like can_see


# Whose approval a change can need, least first. An agent definition names one for each tool that
# writes, and agents/policy.toml sets the least each tool may have (a test keeps the two in step).
APPROVERS = ("staff", "lead")
NEEDS = {"staff": "a member of staff who may change the ticket", "lead": "a lead"}


def may_approve(person: Person, needs: str, ticket: dict[str, Any]) -> bool:
    """May this person approve (or reject) a change that needs this approval, on this ticket?"""
    if not can_change(person, ticket):
        return False
    if needs == "staff":
        return True
    if needs == "lead":
        return person.role == "lead"
    return False  # an approval this rule doesn't know: nobody may give it


def cannot_change(person: Person, ticket: dict[str, Any]) -> str:
    """What a tool says about a ticket the person may see but not change."""
    return (
        f"{person.name} can see ticket {ticket['id']} but can't change it: support staff change only the "
        f"tickets assigned to them. Nothing was filed. Ask a lead to assign it to {person.first_name} first."
    )


def cannot_see(person: Person, ticket_id: int) -> str:
    """What a tool says about a ticket the person can't see. A missing ticket gets the same words,
    so the message never tells anyone which tickets exist."""
    if person.role == "lead":
        return f"Ticket {ticket_id} doesn't exist. Use find_tickets to list the tickets there are."
    rule = RULES.get(person.role, f"the role {person.role!r} sees no tickets")
    return (
        f"{person.name} can't see ticket {ticket_id}: either there is no such ticket, or it's assigned "
        f"to someone else ({rule}). Use find_tickets to list the tickets {person.first_name} can see, and "
        "don't guess what this one says."
    )
