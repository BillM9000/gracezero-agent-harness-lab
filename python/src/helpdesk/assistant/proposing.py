"""The triage assistant's tools that change things (chapter 19). None of them changes anything.

draft_reply and close_ticket act for the person the assistant works for, like every tool (chapter
11), check what that person may change (helpdesk/services/access.py), and file a proposal in the
approval queue. A member of staff approves or rejects it with python -m helpdesk.approvals, and only
then does the ticket change. Whose approval each needs comes from the agent's definition, [approval]
in agents/triage.toml, which the platform's policy checks (chapter 18). A tool that writes can't be
built without one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from helpdesk.assistant.tools import Tool, Toolbox, triage_tools
from helpdesk.model.types import ToolSpec
from helpdesk.services import proposals
from helpdesk.services.access import NEEDS, Person
from helpdesk.services.untrusted import Exposure

# The tools that write, and the kind of proposal each files.
WRITERS = {"draft_reply": "reply", "close_ticket": "close"}

TICKET_ID = {"type": "integer", "minimum": 1, "description": "The ticket's number, such as 2."}

DRAFT_REPLY = ToolSpec(
    "draft_reply",
    "Propose a reply to the customer on one ticket. Nothing is sent: the reply goes into the approval "
    "queue, where a member of staff reads it and approves or rejects it, and this returns the "
    "proposal's number and whose approval it needs. Read the ticket with get_ticket first, including "
    "any changes proposed on it and why they were rejected, and write the whole reply the customer "
    "should get. It works only on tickets the person you work for may change, and one reply per "
    "ticket can wait for approval at a time.",
    {
        "type": "object",
        "properties": {
            "ticket_id": TICKET_ID,
            "reply_text": {
                "type": "string",
                "minLength": 1,
                "description": "The reply, exactly as the customer should read it.",
            },
        },
        "required": ["ticket_id", "reply_text"],
        "additionalProperties": False,
    },
    strict=True,
)

CLOSE_TICKET = ToolSpec(
    "close_ticket",
    "Propose closing one ticket. Nothing changes yet: the proposal goes into the approval queue, and "
    "the ticket closes only when someone with the approval it needs agrees; this returns the "
    "proposal's number and whose approval that is. Give a reason the approver can check against the "
    "ticket. It works only on open or pending tickets the person you work for may change. To answer "
    "the customer, use draft_reply.",
    {
        "type": "object",
        "properties": {
            "ticket_id": TICKET_ID,
            "reason": {
                "type": "string",
                "minLength": 1,
                "description": "Why the ticket can be closed, such as what answered the customer.",
            },
        },
        "required": ["ticket_id", "reason"],
        "additionalProperties": False,
    },
    strict=True,
)


def filed(proposal: dict[str, Any], person: Person) -> str:
    """What the model is told once a proposal is filed: its number, that nothing has changed yet,
    and whose approval it waits for. A change the person can't approve goes to a lead."""
    what = "send this reply on" if proposal["kind"] == "reply" else "close"
    if proposal["needs"] == "lead" and person.role != "lead":
        whose = (
            f"It needs a lead's approval, and {person.name} is {person.role}, so it waits for a lead. "
            f"Tell {person.first_name} that a lead has to approve it."
        )
    else:
        whose = (
            f"It needs approval by {NEEDS[proposal['needs']]}, which {person.name} can give. "
            f"Tell {person.first_name} it's waiting in the approval queue."
        )
    number, ticket_id = proposal["id"], proposal["ticket_id"]
    return f"Filed proposal #{number}: {what} ticket {ticket_id}. Nothing has changed yet. {whose}"


def proposing_tools(
    conn: sqlite3.Connection,
    person: Person,
    agent: str,
    approval: Mapping[str, str],
    exposure: Exposure | None = None,
) -> Toolbox:
    """A writer for each tool in approval, filing proposals for this agent and person, each needing
    the approval named for it. Each proposal carries the flags on what the run had read by then
    (chapter 20), from the exposure the reading tools share."""
    seen = exposure if exposure is not None else Exposure()

    def draft_reply(ticket_id: int, reply_text: str) -> str:
        proposal = proposals.propose(
            conn, person, agent, "reply", ticket_id, reply_text, approval["draft_reply"], flags=seen.flags
        )
        return filed(proposal, person)

    def close_ticket(ticket_id: int, reason: str) -> str:
        proposal = proposals.propose(
            conn, person, agent, "close", ticket_id, reason, approval["close_ticket"], flags=seen.flags
        )
        return filed(proposal, person)

    built = {"draft_reply": Tool(DRAFT_REPLY, draft_reply, writes=True)}
    built["close_ticket"] = Tool(CLOSE_TICKET, close_ticket, writes=True)
    return Toolbox(built[name] for name in approval if name in built)


def assistant_tools(conn: sqlite3.Connection, person: Person, definition: Mapping[str, Any]) -> Toolbox:
    """The tools an agent definition gives its agent, acting for one person: chapter 11's readers,
    and chapter 19's writers, each needing the approval the definition names for it."""
    names: list[str] = definition["tools"]
    approval: Mapping[str, str] = definition.get("approval", {})
    unapproved = [name for name in names if name in WRITERS and name not in approval]
    if unapproved:
        raise ValueError(
            f"{', '.join(unapproved)} change things, and {definition['name']}'s definition doesn't say "
            "whose approval they need. Add them under [approval]; python -m agent_policy says the least "
            "each may have."
        )
    # One exposure for the run: what the readers see that customers wrote, the writers report.
    exposure = Exposure()
    writers = proposing_tools(
        conn, person, definition["name"], {n: approval[n] for n in names if n in WRITERS}, exposure
    )
    return triage_tools(conn, person, exposure).plus(*writers.tools).only(names)
