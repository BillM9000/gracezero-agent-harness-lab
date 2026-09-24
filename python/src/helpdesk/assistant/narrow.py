"""A narrow tool set, kept only to be measured against (chapter 11).

This is the shape many first tool sets take: one tool for each table or endpoint, each returning
its rows as JSON. The triage assistant never gets it. python -m helpdesk.tools compare gives the
same tasks to this set and to the triage set, so the difference between them is measured rather
than asserted. It keeps every rule the triage tools keep (it acts for one person, its schemas are
strict, its descriptions are as full), so the only difference is the shape.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from helpdesk.assistant.tools import Tool, Toolbox, search_kb_tool
from helpdesk.model.types import ToolSpec
from helpdesk.services import access, tickets
from helpdesk.services.access import Person
from helpdesk.services.errors import NotFound


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _id(what: str) -> dict[str, Any]:
    return {"type": "integer", "minimum": 1, "description": f"The {what}'s id, 1 or more."}


def narrow_tools(conn: sqlite3.Connection, person: Person) -> Toolbox:
    def get_ticket(ticket_id: int) -> str:
        return json.dumps(tickets.visible_ticket(conn, person, ticket_id))

    def list_tickets(status: str | None = None) -> str:
        return json.dumps(tickets.visible_tickets(conn, person, status))

    def get_customer(customer_id: int) -> str:
        return json.dumps(tickets.customer_for(conn, person, customer_id))

    def list_customer_tickets(customer_id: int) -> str:
        return json.dumps(tickets.tickets_for_customer(conn, person, customer_id))

    def get_staff(staff_id: int) -> str:
        # The staff list is no secret from other staff, so this needs no check beyond existing.
        found = [p for p in access.staff(conn) if p.id == staff_id]
        if not found:
            raise NotFound(f"There is no member of staff {staff_id}.")
        return json.dumps({"id": found[0].id, "name": found[0].name, "role": found[0].role})

    def spec(name: str, description: str, schema: dict[str, Any]) -> ToolSpec:
        return ToolSpec(name, description, schema, strict=True)

    return Toolbox(
        [
            Tool(
                spec(
                    "get_ticket",
                    "Get one ticket by id, as a JSON object with its replies. Fields include "
                    "customer_id and assignee_id; look those up with get_customer and get_staff. It "
                    "returns only tickets the person you work for may see.",
                    _schema({"ticket_id": _id("ticket")}, ["ticket_id"]),
                ),
                get_ticket,
            ),
            Tool(
                spec(
                    "list_tickets",
                    "List every ticket the person you work for may see, as a JSON array, in id order. "
                    "Pass status to list only open, pending or closed tickets. Use get_ticket for one "
                    "ticket's replies.",
                    _schema(
                        {
                            "status": {
                                "type": "string",
                                "enum": list(tickets.STATUSES),
                                "description": "Only tickets with this status; every status if left out.",
                            }
                        },
                        [],
                    ),
                ),
                list_tickets,
            ),
            Tool(
                spec(
                    "get_customer",
                    "Get one customer by id, as a JSON object with their name. It returns only customers "
                    "with a ticket the person you work for may see. Use list_customer_tickets for their "
                    "tickets.",
                    _schema({"customer_id": _id("customer")}, ["customer_id"]),
                ),
                get_customer,
            ),
            Tool(
                spec(
                    "list_customer_tickets",
                    "List one customer's tickets that the person you work for may see, as a JSON array, "
                    "in id order. Each has the same fields as get_ticket, without replies. Use it to "
                    "see whether a customer has written in before.",
                    _schema({"customer_id": _id("customer")}, ["customer_id"]),
                ),
                list_customer_tickets,
            ),
            Tool(
                spec(
                    "get_staff",
                    "Get one member of staff by id, as a JSON object with their name and role. Use it to "
                    "turn an assignee_id or a reply's author_id into a name. Customers are not staff; "
                    "use get_customer for them.",
                    _schema({"staff_id": _id("member of staff")}, ["staff_id"]),
                ),
                get_staff,
            ),
            search_kb_tool(conn),
        ]
    )
