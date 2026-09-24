"""Checking a tool call's arguments before anything runs (chapter 11).

A provider's strict mode constrains the model's arguments to the schema's shape, where it's on. It
doesn't enforce ranges or lengths, doesn't guarantee an enum value's capitalization, and can't know
whether a well-formed ticket number means anything. The toolbox checks the whole schema itself,
every call, and reports every problem at once.
"""

from __future__ import annotations

from helpdesk.assistant.tools import Tool, Toolbox, checked_arguments, triage_tools
from helpdesk.model.types import ToolCall, ToolSpec
from helpdesk.services import access


def call(conn, name, **arguments):
    return triage_tools(conn, access.find_person(conn, "sam")).run(ToolCall("c1", name, arguments))


def test_every_problem_is_reported_at_once(conn):
    result = call(conn, "find_tickets", status="solved", page=0, owner="me")
    assert result.is_error
    assert result.content == (
        "find_tickets wasn't run, because of 3 problems: owner isn't one of its arguments (it takes "
        'status, assignee, page); status must be "open", "pending", "closed" or "any", not "solved"; '
        "page must be 1 or more, not 0. Call it again with all 3 fixed."
    )


def test_an_enum_value_in_another_case_is_taken_as_the_schemas_own(conn):
    result = call(conn, "find_tickets", status="Open", assignee="ME")
    assert not result.is_error
    assert result.content.startswith("Tickets Sam Rivera can see (open, assigned to Sam Rivera): 2,")


def test_a_number_below_the_minimum_is_refused(conn):
    # Strict mode would pass these: its schemas can't carry a minimum.
    assert call(conn, "get_ticket", ticket_id=0).content == (
        "get_ticket wasn't run: ticket_id must be 1 or more, not 0. Call it again with that fixed."
    )
    assert "page must be 1 or more, not -1" in call(conn, "find_tickets", page=-1).content


def test_empty_text_is_refused(conn):
    assert call(conn, "search_kb", query="   ").content == (
        "search_kb wasn't run: query must not be empty. Call it again with that fixed."
    )


def test_a_value_of_the_wrong_type_is_refused_and_shown(conn):
    assert (
        'ticket_id must be a whole number, not "four"' in call(conn, "get_ticket", ticket_id="four").content
    )
    assert "ticket_id must be a whole number, not true" in call(conn, "get_ticket", ticket_id=True).content
    assert "query must be text, not 3" in call(conn, "search_kb", query=3).content


def test_nothing_runs_when_the_arguments_are_wrong():
    ran = []
    spec = ToolSpec(
        "count",
        "Count.",
        {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 3}},
            "required": ["n"],
            "additionalProperties": False,
        },
    )
    box = Toolbox([Tool(spec, lambda n: ran.append(n) or "ok")])
    assert box.run(ToolCall("c1", "count", {"n": 4})).content == (
        "count wasn't run: n must be 3 or less, not 4. Call it again with that fixed."
    )
    assert ran == []
    assert box.run(ToolCall("c2", "count", {"n": 3})).content == "ok"
    assert ran == [3]


def test_checked_arguments_returns_what_the_tool_should_get():
    spec = ToolSpec("t", "T.", {"type": "object", "properties": {"s": {"type": "string", "enum": ["open"]}}})
    assert checked_arguments(spec, {"s": "OPEN"}) == ({"s": "open"}, [])
