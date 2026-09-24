"""The tools the triage assistant may use, and the code that runs them (chapters 3, 9 and 11).

A tool is the interface a model reasons from: its name, its description, its schema and what it
returns. Since chapter 11, every tool here:

- acts for one member of staff, fixed when the toolbox is built, and shows only what that person
  may see (helpdesk/services/access.py). No tool takes the person as an argument;
- declares a strict schema, and the toolbox checks every call against it before anything runs,
  including the parts a provider's strict mode can't enforce;
- answers a bad call with an error that says what was wrong and what to do next;
- returns a result sized for a context window: find_tickets pages, and the toolbox cuts any result
  longer than MAX_RESULT_CHARS and says so.

Every tool here only reads. Tools that change a ticket arrive with human approval in chapter 19.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from helpdesk.model.types import ToolCall, ToolResult, ToolSpec
from helpdesk.services import kb, tickets
from helpdesk.services.access import Person
from helpdesk.services.errors import ServiceError

log = logging.getLogger(__name__)

# The longest result the toolbox sends back whole, in characters: about 2,400 tokens at the 2.5
# characters per token Anthropic's models page gives. A page of tickets is under 1,000, so this is
# a backstop for a tool or a ticket that is misbehaving, not a size any tool aims for.
MAX_RESULT_CHARS = 6000

# The JSON Schema types the toolbox checks, and how each is described in an error.
JSON_TYPES: dict[str, tuple[type, str]] = {"integer": (int, "a whole number"), "string": (str, "text")}


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    run: Callable[..., str]
    # What to do when a result is too long to send whole: how to ask for less.
    narrower: str = "Ask for less at a time."


class Toolbox:
    def __init__(self, tools: Iterable[Tool], max_result_chars: int = MAX_RESULT_CHARS) -> None:
        self._tools = {t.spec.name: t for t in tools}
        self.max_result_chars = max_result_chars

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
        return Toolbox((self._tools[name] for name in wanted), self.max_result_chars)

    def limited(self, max_result_chars: int) -> Toolbox:
        """The same tools, cutting results at a different length."""
        return Toolbox(self._tools.values(), max_result_chars)

    def run(self, call: ToolCall) -> ToolResult:
        """Run one call. Every failure comes back as a result the model can read and act on."""
        tool = self._tools.get(call.name)
        if tool is None:
            known = ", ".join(sorted(self._tools))
            return ToolResult(
                call.id, f"There is no tool named {call.name!r}. Available tools: {known}.", is_error=True
            )
        arguments, problems = checked_arguments(tool.spec, call.arguments)
        if problems:
            return ToolResult(call.id, not_run(tool.spec.name, problems), is_error=True)
        try:
            content = tool.run(**arguments)
        except ServiceError as e:
            return ToolResult(call.id, str(e), is_error=True)
        except Exception as e:
            # A fault in the tool, not in the call. The person debugging gets the traceback; the
            # model gets what it can act on, which is not to try the same call again.
            log.exception("tool %s failed", call.name)
            return ToolResult(
                call.id,
                f"{call.name} failed with an unexpected {type(e).__name__}. That is a fault in the tool, "
                "not in your arguments, so calling it again the same way won't help. Tell the person "
                "this tool failed, and carry on without it if you can.",
                is_error=True,
            )
        return ToolResult(call.id, self._fitted(tool, content))

    def _fitted(self, tool: Tool, content: str) -> str:
        """The result, cut at a line boundary if it's longer than the limit, with a line saying so."""
        if len(content) <= self.max_result_chars:
            return content
        cut = content[: self.max_result_chars]
        if "\n" in cut:
            cut = cut[: cut.rindex("\n")]
        return (
            f"{cut}\n[Cut: this result was {len(content):,} characters, and only the first {len(cut):,} "
            f"are shown. {tool.narrower}]"
        )


def checked_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Check a call's arguments against the tool's schema before the tool runs, and report every
    problem at once, so one retry can fix them all. Returns the arguments to use (an enum value in
    the wrong case becomes the schema's own) and the problems, if any."""
    properties: dict[str, dict[str, Any]] = spec.input_schema.get("properties", {})
    problems = [
        f"{name} is missing" for name in spec.input_schema.get("required", []) if name not in arguments
    ]
    takes = ", ".join(properties) or "no arguments"
    problems += [
        f"{name} isn't one of its arguments (it takes {takes})"
        for name in arguments
        if name not in properties
    ]
    fixed = {}
    for name, value in arguments.items():
        rules = properties.get(name)
        if rules is None:
            continue
        problem, value = checked_value(name, value, rules)
        if problem:
            problems.append(problem)
        fixed[name] = value
    return fixed, problems


def checked_value(name: str, value: Any, rules: dict[str, Any]) -> tuple[str | None, Any]:
    """One argument against its schema: type, allowed values, range and emptiness."""
    kind, described = JSON_TYPES.get(rules.get("type", ""), (object, "a value"))
    # In Python, True is an int. In a tool call it's a mistake.
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        return f"{name} must be {described}, not {json.dumps(value)}", value
    if "enum" in rules:
        # Anthropic's docs warn that strict mode doesn't guarantee an enum value's capitalization,
        # and advise comparing without case. "Open" is taken as "open".
        same = [allowed for allowed in rules["enum"] if str(allowed).lower() == str(value).lower()]
        if not same:
            *most, last = [json.dumps(a) for a in rules["enum"]]
            allowed = f"{', '.join(most)} or {last}" if most else last
            return f"{name} must be {allowed}, not {json.dumps(value)}", value
        value = same[0]
    if "minimum" in rules and value < rules["minimum"]:
        return f"{name} must be {rules['minimum']} or more, not {value}", value
    if "maximum" in rules and value > rules["maximum"]:
        return f"{name} must be {rules['maximum']} or less, not {value}", value
    if "minLength" in rules and len(value.strip()) < rules["minLength"]:
        return f"{name} must not be empty", value
    return None, value


def not_run(tool: str, problems: list[str]) -> str:
    if len(problems) == 1:
        return f"{tool} wasn't run: {problems[0]}. Call it again with that fixed."
    count = len(problems)
    fixed = "both" if count == 2 else f"all {count}"
    listed = "; ".join(problems)
    return f"{tool} wasn't run, because of {count} problems: {listed}. Call it again with {fixed} fixed."


# The triage assistant's tools as the model sees them. Each description says what the tool returns,
# when to use it and when to use another, and what it won't do; tests/fitness/test_tool_definitions.py
# checks the parts of that a test can check.

GET_TICKET = ToolSpec(
    "get_ticket",
    "Read one ticket in full: its subject, status, priority and text, the customer's name, who it's "
    "assigned to, every reply so far with its author, and the customer's other tickets. Use it before "
    "drafting a reply, and to see whether the customer has written in before. It reads only tickets the "
    "person you work for may see; for any other number it says so, and you should tell the person rather "
    "than guess. To find tickets by status or assignee, use find_tickets.",
    {
        "type": "object",
        "properties": {
            "ticket_id": {"type": "integer", "minimum": 1, "description": "The ticket's number, such as 4."}
        },
        "required": ["ticket_id"],
        "additionalProperties": False,
    },
    strict=True,
)

FIND_TICKETS = ToolSpec(
    "find_tickets",
    "List the tickets the person you work for may see, in the order to handle them: high priority "
    "first, then oldest first. Filter by status and by assignee. Returns five tickets a page, each with "
    "its number, status, priority, subject, customer and assignee, and says how many match and how many "
    "pages there are. Use get_ticket to read one ticket in full, and search_kb for help articles.",
    {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": list(tickets.STATUS_FILTERS),
                "description": 'Leave it out for open and pending tickets; "any" includes closed ones.',
            },
            "assignee": {
                "type": "string",
                "enum": list(tickets.ASSIGNEES),
                "description": '"me" for tickets assigned to the person you work for, "unassigned" for '
                'the queue, "anyone" (the default) for every ticket they may see.',
            },
            "page": {"type": "integer", "minimum": 1, "description": "Which page, from 1; 1 if left out."},
        },
        "required": [],
        "additionalProperties": False,
    },
    strict=True,
)

SEARCH_KB = ToolSpec(
    "search_kb",
    "Search the help articles in plain words, such as the customer's question. Returns up to three "
    "passages, best first, each starting with an id in square brackets to cite, such as [1#2], and says "
    "so when nothing matches. Use it for how the product works; for tickets, use get_ticket or "
    "find_tickets.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "description": "What to look for, in words."}
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    strict=True,
)


def search_kb_tool(conn: sqlite3.Connection) -> Tool:
    """The knowledge-base search (chapter 9). Help articles are for every member of staff, so it
    needs no person."""

    def search_kb(query: str) -> str:
        # Each passage on its own line, id first, which is how citations.passages_in reads it back.
        hits = kb.retrieve(conn, query)
        if not hits:
            return f"Nothing in the knowledge base matches {query!r}. Say so in the reply; don't guess."
        return "\n".join(f"[{hit.chunk.id}] {hit.chunk.indexed}" for hit in hits)

    return Tool(SEARCH_KB, search_kb)


def triage_tools(conn: sqlite3.Connection, person: Person) -> Toolbox:
    """The triage assistant's tools, acting for one member of staff."""

    def get_ticket(ticket_id: int) -> str:
        ticket = tickets.ticket_in_context(conn, person, ticket_id)
        assigned = f"Assigned to {ticket['assignee_name']}." if ticket["assignee_name"] else "Unassigned."
        lines = [
            f"Ticket {ticket['id']} [{ticket['status']}, {ticket['priority']} priority]: {ticket['subject']}",
            f"From {ticket['customer_name']}, opened {ticket['created_at'][:10]}. {assigned}",
            ticket["body"],
        ]
        if ticket["replies"]:
            lines.append("Replies, oldest first:")
            lines += [
                f"  {r['author_name']} ({r['author_kind']}), {r['created_at'][:10]}: {r['body']}"
                for r in ticket["replies"]
            ]
        else:
            lines.append("No replies yet.")
        others = [
            f"#{t['id']} [{t['status']}] {t['subject']} ({t['created_at'][:10]})"
            for t in ticket["other_tickets"]
        ]
        whose = f"{ticket['customer_name']}'s other tickets that {person.name} can see"
        lines.append(f"{whose}: {'; '.join(others) or 'none'}.")
        return "\n".join(lines)

    def find_tickets(status: str | None = None, assignee: str = "anyone", page: int = 1) -> str:
        found = tickets.find_tickets(conn, person, status, assignee, page)
        which = {None: "open or pending", "any": "any status"}.get(status, status)
        whom = {"me": f"assigned to {person.name}", "unassigned": "unassigned", "anyone": "any assignee"}
        filters = f"{which}, {whom[assignee]}"
        if not found.total:
            return (
                f"No tickets that {person.name} can see match ({filters}). To widen the search, leave "
                'status out or use "any", and use assignee "anyone".'
            )
        lines = [
            f"Tickets {person.name} can see ({filters}): {found.total}, highest priority first. "
            f"Page {found.page} of {found.pages}."
        ]
        for t in found.tickets:
            lines.append(
                f"#{t['id']} [{t['status']}, {t['priority']}] {t['subject']} ({t['customer_name']}; "
                f"{t['assignee_name'] or 'unassigned'}; opened {t['created_at'][:10]})"
            )
        if found.page < found.pages:
            n = found.page + 1
            lines.append(f"More on page {n}: call find_tickets again with the same filters and page {n}.")
        else:
            lines.append("That's all of them.")
        return "\n".join(lines)

    too_long = "The end is cut: tell the person this ticket is too long to read whole here."
    fewer = "Use the status or assignee filters to ask for fewer tickets."
    return Toolbox(
        [
            Tool(GET_TICKET, get_ticket, narrower=too_long),
            Tool(FIND_TICKETS, find_tickets, narrower=fewer),
            search_kb_tool(conn),
        ]
    )
