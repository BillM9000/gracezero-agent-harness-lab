"""The golden path's rules (chapter 29), as pure functions.

answer_problems(...) says what's wrong with a team's answers before anything is written. render(...)
fills the path's two templates with them; every answer goes in as a TOML string, so no answer can
change a file's shape. state(...) applies the golden state: the checks that say whether a use case is
on the golden path, however it started. They read no files and call nothing, so the tests can pin
exactly what they accept.
"""

from __future__ import annotations

import json
import re
import textwrap
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import date
from string import Template
from typing import Any

from readiness.rules import FIELDS, Result

# A name becomes two file names and a gateway route, so it's kept to what's safe in all three.
NAME = re.compile(r"[a-z][a-z0-9-]{2,39}")
# The longest one-line answers the path takes.
LONGEST = {"champion": 60, "problem": 300}


@dataclass(frozen=True)
class Answers:
    name: str
    team: str
    champion: str
    problem: str


def answer_problems(answers: Answers, teams: Collection[str], taken: Collection[str]) -> list[str]:
    """Everything wrong with a team's answers, each with what to do instead."""
    problems = []
    if not NAME.fullmatch(answers.name):
        problems.append(
            f"name: {json.dumps(answers.name)} must be 3 to 40 lowercase letters, digits and hyphens, "
            "starting with a letter: it names the agent, its use case and its route."
        )
    elif answers.name in taken:
        problems.append(
            f"name: {answers.name} is taken (agents/{answers.name}.toml or usecases/{answers.name}.toml). "
            "Pick another name, or change that use case by hand."
        )
    if answers.team not in teams:
        problems.append(
            f"team: {json.dumps(answers.team)} isn't a team in agents/policy.toml, so nothing would limit "
            "what it spends (chapter 27). Ask the platform team to add it with a monthly budget, then "
            "run this again."
        )
    for field in ("champion", "problem"):
        text = getattr(answers, field)
        if not text.strip():
            problems.append(f"{field}: empty. {FIELDS[field][1]}")
        elif len(text) > LONGEST[field] or any(ord(c) < 32 or ord(c) == 127 for c in text):
            problems.append(f"{field}: must be one line of at most {LONGEST[field]} characters.")
    return problems


def toml_string(text: str) -> str:
    """A TOML basic string whose value is exactly text. JSON's escapes are TOML's too; DEL is the one
    character TOML wants escaped that JSON leaves alone."""
    return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007f")


def toml_text(text: str, width: int = 96) -> str:
    """A multi-line TOML string whose value is exactly text, as agents/triage.toml writes its prompt:
    each paragraph on its own lines, wrapped with TOML's line-ending backslash, which drops the line
    break and the next line's indentation. text has single spaces between words."""
    paragraphs = []
    for paragraph in text.split("\n"):
        lines = textwrap.wrap(paragraph, width, break_long_words=False, break_on_hyphens=False) or [""]
        escaped = [line.replace("\\", "\\\\").replace('"', '\\"') for line in lines]
        paragraphs.append(" \\\n".join(escaped))
    return '"""\n' + "\n".join(paragraphs) + '"""'


def system_prompt(answers: Answers, template: Mapping[str, Any]) -> str:
    """The team's job in its own words, then the platform's standard text, a paragraph each."""
    problem = " ".join(answers.problem.split())
    opening = Template(template["prompt"]["opening"]).substitute(problem=problem)
    return "\n\n".join([opening, *template["standard"].values()])


def render(
    answers: Answers, template: Mapping[str, Any], tier: str, agent_tmpl: str, use_case_tmpl: str
) -> tuple[str, str]:
    """The agent definition and the use case the path writes for these answers, as file text."""
    intake = template["intake"]
    values = {
        "title": answers.name,
        "version": str(int(template["version"])),
        "name": toml_string(answers.name),
        "team": toml_string(answers.team),
        "champion": toml_string(" ".join(answers.champion.split())),
        "problem": toml_string(" ".join(answers.problem.split())),
        "model": toml_string(template["model"]),
        "max_tokens": str(int(template["max_tokens"])),
        "max_turns": str(int(template["max_turns"])),
        "tools": json.dumps(list(template["tools"])),
        "needs": json.dumps(list(template["needs"])),
        "tier": toml_string(tier),
        "acts": toml_string(intake["acts"]),
        "data": toml_string(intake["data"]),
        "audience": toml_string(intake["audience"]),
        "system": toml_text(system_prompt(answers, template)),
    }
    return Template(agent_tmpl).substitute(values), Template(use_case_tmpl).substitute(values)


# --- The golden state: is a use case on the golden path?


def in_force(record: Mapping[str, Any], today: date) -> list[Mapping[str, Any]]:
    """The use case's readiness exceptions (chapter 29) that haven't ended."""
    return [
        e
        for e in record.get("exceptions", [])
        if isinstance(e, Mapping) and isinstance(e.get("until"), date) and e["until"] >= today
    ]


def builds_on_the_library(record, definition, template, library, today) -> tuple[bool, str]:
    missing = [need for need in record.get("needs", []) if need not in library]
    if missing:
        return False, f"{', '.join(map(json.dumps, missing))} isn't in the library"
    return True, "builds only on the library"


def carries_the_standard_text(record, definition, template, library, today) -> tuple[bool, str]:
    if definition is None:
        return False, "no agent definition yet"
    missing = [
        name for name, text in template["standard"].items() if text not in definition.get("system", "")
    ]
    if missing:
        which = ", ".join(missing)
        return False, (
            f"agents/{record['agent']}.toml doesn't carry the platform's standard text ({which}) word for "
            "word. Copy it from golden-path/template.toml."
        )
    return True, "carries the platform's standard text"


def nothing_excused(record, definition, template, library, today) -> tuple[bool, str]:
    excused = in_force(record, today)
    if excused:
        return False, "; ".join(f"{e['item']} excused until {e['until']}" for e in excused)
    return True, "nothing excused"


# Every check in golden-path/template.toml's [[state]], and the function behind it. A test keeps the
# two in step.
STATE: dict[str, Callable[..., tuple[bool, str]]] = {
    "library": builds_on_the_library,
    "standard-text": carries_the_standard_text,
    "exceptions": nothing_excused,
}


def state(
    record: Mapping[str, Any],
    definition: Mapping[str, Any] | None,
    template: Mapping[str, Any],
    library: Collection[str],
    today: date,
) -> list[Result]:
    """The golden state's checks, in template.toml's order. A use case is on the golden path when
    every one passes."""
    return [
        Result(s["id"], *STATE[s["id"]](record, definition, template, library, today))
        for s in template["state"]
    ]
