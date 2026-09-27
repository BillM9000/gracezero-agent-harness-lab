"""Checking a tool call's arguments before anything runs (chapter 11).

A provider's strict mode constrains the model's arguments to the schema's shape, where it's on. It
doesn't enforce ranges or lengths, doesn't guarantee an enum value's capitalization, and can't know
whether a well-formed ticket number means anything. The toolbox checks the whole schema itself,
every call, and reports every problem at once.
"""

from __future__ import annotations

import pytest

from helpdesk.assistant.tools import ARGUMENT_KEYWORDS, Tool, Toolbox, checked_arguments, triage_tools
from helpdesk.model.anthropic_client import STRICT_UNSUPPORTED
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


def one_argument(rules, **schema):
    """A strict tool taking one argument, n, with these rules."""
    spec = ToolSpec(
        "t",
        "T.",
        {
            "type": "object",
            "properties": {"n": rules},
            "required": ["n"],
            "additionalProperties": False,
            **schema,
        },
        strict=True,
    )
    return Tool(spec, lambda n: "ok")


def test_a_toolbox_refuses_a_schema_rule_it_cant_check():
    # The Anthropic adapter strips these from what it sends, so nothing would check them.
    with pytest.raises(ValueError) as refused:
        Toolbox([one_argument({"type": "integer", "exclusiveMinimum": 0, "multipleOf": 2})])
    assert str(refused.value) == (
        "The toolbox can't check t.n's 'exclusiveMinimum'; t.n's 'multipleOf'. Nothing would enforce it: "
        "the Anthropic adapter strips what strict mode can't carry because the toolbox checks it. Use only "
        "the rules in ARGUMENT_KEYWORDS, or teach checked_value the new one first."
    )
    planted = [
        ({"type": "string", "maxLength": 5}, "t.n's 'maxLength'"),
        ({"type": "string", "pattern": "^a"}, "t.n's 'pattern'"),
        ({"type": "string", "minimum": 1}, "t.n's 'minimum'"),
        ({"type": "number"}, "t.n's type 'number'"),
        ({"type": "boolean"}, "t.n's type 'boolean'"),
        ({"type": "array", "items": {"type": "integer"}, "maxItems": 3}, "t.n's type 'array'"),
        ({"description": "No type at all."}, "t.n's type None"),
    ]
    for rules, named in planted:
        with pytest.raises(ValueError, match=f"^The toolbox can't check {named}[.]"):
            Toolbox([one_argument(rules)])
    with pytest.raises(ValueError, match="^The toolbox can't check t's 'minProperties'[.]"):
        Toolbox([one_argument({"type": "integer"}, minProperties=1)])
    with pytest.raises(ValueError, match="^The toolbox can't check t's type 'array'"):
        Toolbox([Tool(ToolSpec("t", "T.", {"type": "array"}), lambda: "ok")])


def test_every_keyword_the_adapter_strips_is_checked_or_refused():
    # A value each checked keyword refuses when set to 2.
    breaking = {"minimum": 1, "maximum": 3, "minLength": " a "}
    for key in (*STRICT_UNSUPPORTED, "minItems"):
        for kind in ARGUMENT_KEYWORDS:
            tool = one_argument({"type": kind, key: 2})
            if key not in ARGUMENT_KEYWORDS[kind]:
                with pytest.raises(ValueError, match=f"^The toolbox can't check t.n's '{key}'"):
                    Toolbox([tool])
                continue
            result = Toolbox([tool]).run(ToolCall("c1", "t", {"n": breaking[key]}))
            assert result.is_error, f"{kind} with {key} = 2 passed {breaking[key]!r}"
