"""The tools the triage assistant may use, and the code that runs them.

Chapter 3's tools only read. Tools that change things, such as drafting a reply or closing a
ticket, arrive with the chapters on tool design and human approval.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from helpdesk.model.types import ToolCall, ToolResult, ToolSpec
from helpdesk.services import kb, tickets
from helpdesk.services.errors import ServiceError

JSON_TYPES: dict[str, type | tuple[type, ...]] = {"integer": int, "string": str}


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    run: Callable[..., str]


class Toolbox:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools = {t.spec.name: t for t in tools}

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(t.spec for t in self._tools.values())

    def only(self, names: Iterable[str]) -> Toolbox:
        """The named tools, in that order. A name this toolbox doesn't have is an error, never a skip."""
        wanted = list(names)
        missing = [name for name in wanted if name not in self._tools]
        if missing:
            known = ", ".join(sorted(self._tools))
            raise KeyError(f"No tool named {', '.join(missing)}. Available tools: {known}.")
        return Toolbox(self._tools[name] for name in wanted)

    def run(self, call: ToolCall) -> ToolResult:
        """Run one call. Every failure comes back as a result the model can read and act on."""
        tool = self._tools.get(call.name)
        if tool is None:
            known = ", ".join(sorted(self._tools))
            return ToolResult(
                call.id, f"There is no tool named {call.name!r}. Available tools: {known}.", is_error=True
            )
        problem = argument_problem(tool.spec, call.arguments)
        if problem:
            return ToolResult(call.id, problem, is_error=True)
        try:
            return ToolResult(call.id, tool.run(**call.arguments))
        except ServiceError as e:
            return ToolResult(call.id, str(e), is_error=True)


def argument_problem(spec: ToolSpec, arguments: dict[str, Any]) -> str | None:
    """Check arguments against the tool's schema before running it. None means they're fine."""
    properties = spec.input_schema.get("properties", {})
    missing = [name for name in spec.input_schema.get("required", []) if name not in arguments]
    if missing:
        return f"{spec.name} needs {', '.join(missing)}. Call it again with every required argument."
    unknown = [name for name in arguments if name not in properties]
    if unknown:
        return f"{spec.name} does not take {', '.join(unknown)}. It takes: {', '.join(properties)}."
    for name, value in arguments.items():
        expected = JSON_TYPES.get(properties[name].get("type", ""))
        if expected and (not isinstance(value, expected) or isinstance(value, bool)):
            return f"{spec.name}: {name} must be of type {properties[name]['type']}; got {value!r}."
    return None


def triage_tools(conn: sqlite3.Connection) -> Toolbox:
    def get_ticket(ticket_id: int) -> str:
        ticket = tickets.get_ticket(conn, ticket_id)
        lines = [
            f"Ticket {ticket['id']} [{ticket['status']}, {ticket['priority']} priority]: {ticket['subject']}",
            ticket["body"],
        ]
        lines += [f"Reply from {r['author_kind']}: {r['body']}" for r in ticket["replies"]]
        return "\n".join(lines)

    def search_kb(query: str) -> str:
        articles = kb.search(conn, query)
        if not articles:
            return f"No knowledge-base article matches {query!r}. Try one shorter keyword."
        return "\n".join(f"Article {a['id']}, {a['title']}: {a['body']}" for a in articles)

    return Toolbox(
        [
            Tool(
                ToolSpec(
                    "get_ticket",
                    "Read one helpdesk ticket by its number, with any replies so far.",
                    {
                        "type": "object",
                        "properties": {"ticket_id": {"type": "integer", "description": "The ticket number."}},
                        "required": ["ticket_id"],
                    },
                ),
                get_ticket,
            ),
            Tool(
                ToolSpec(
                    "search_kb",
                    "Search the knowledge base for articles containing a keyword. Short keywords work best.",
                    {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "One keyword, such as password."}
                        },
                        "required": ["query"],
                    },
                ),
                search_kb,
            ),
        ]
    )
