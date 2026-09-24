"""Fitness function: every tool is described well enough to reason from (chapter 11).

A model knows a tool only by its name, its description and its schema. Anthropic's tool-use
documentation calls the description the most important factor in how well a tool is used, and
asks for at least three or four sentences; its engineering post on tools asks for unambiguous
parameter names, such as user_id rather than user. A test can't judge whether a description is
good, but it can catch one that is missing its parts. This walks every tool set the code defines,
so a tool added later is checked without anyone remembering to add it.
"""

from __future__ import annotations

import re

from helpdesk.assistant.narrow import narrow_tools
from helpdesk.assistant.team import Team, orchestrator_tools
from helpdesk.assistant.tools import triage_tools
from helpdesk.model.mock import MockModel
from helpdesk.model.types import ToolSpec
from helpdesk.services.access import Person


def team_tools(conn, person):
    """Chapter 14's orchestrator's tools. No worker starts, so its model is never called."""
    return orchestrator_tools(Team(conn, person, lambda _customer: MockModel([]), system="", known=()))


SETS = {"triage": triage_tools, "narrow": narrow_tools, "orchestrator": team_tools}
# Names that leave the model guessing what to pass: an id, a name, or the whole record?
AMBIGUOUS = {"id", "user", "ticket", "customer", "staff", "person"}
MIN_SENTENCES = 3


def sentences(text: str) -> int:
    return len(re.findall(r"[.!?](?=\s|$)", text))


def problems(spec: ToolSpec) -> list[str]:
    found = []
    if sentences(spec.description) < MIN_SENTENCES:
        found.append(f"{spec.name}: the description has fewer than {MIN_SENTENCES} sentences")
    schema = spec.input_schema
    if schema.get("additionalProperties") is not False:
        found.append(f"{spec.name}: the schema must set additionalProperties to false")
    if not spec.strict:
        found.append(f"{spec.name}: the tool must be marked strict")
    for name, rules in schema.get("properties", {}).items():
        if not rules.get("description", "").strip():
            found.append(f"{spec.name}.{name}: every parameter needs a description")
        if name in AMBIGUOUS:
            found.append(f"{spec.name}.{name}: name it for what it holds, such as {name}_id")
    return found


def every_spec(conn) -> list[ToolSpec]:
    anyone = Person(1, "Any One", "support")
    return [spec for build in SETS.values() for spec in build(conn, anyone).specs]


def test_every_tool_is_described_well_enough_to_reason_from(conn):
    found = [problem for spec in every_spec(conn) for problem in problems(spec)]
    assert not found, "\n".join(found)


def test_a_thin_definition_is_caught_with_each_problem_named():
    thin = ToolSpec(
        "lookup", "Looks things up.", {"type": "object", "properties": {"user": {"type": "string"}}}
    )
    assert problems(thin) == [
        "lookup: the description has fewer than 3 sentences",
        "lookup: the schema must set additionalProperties to false",
        "lookup: the tool must be marked strict",
        "lookup.user: every parameter needs a description",
        "lookup.user: name it for what it holds, such as user_id",
    ]
