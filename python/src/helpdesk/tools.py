"""Composition root for the triage assistant's tools on the command line (chapter 11).

python -m helpdesk.tools list                          the tools as the model sees them, and their size
python -m helpdesk.tools list --set narrow             the same for the narrow set kept for comparison
python -m helpdesk.tools schema find_tickets           one tool as the Anthropic adapter sends it
python -m helpdesk.tools call get_ticket ticket_id=4   run one call as a member of staff (--as, default
                                                       sam) and print what the model would get back
python -m helpdesk.tools compare                       the same tasks with the narrow set and the
                                                       triage set, measured

A call's arguments are NAME=VALUE pairs. A value that reads as JSON is taken as JSON, so
ticket_id=4 is the number 4; anything else is text, so status=open is "open". Each run loads the
sample data into a fresh in-memory database, so nothing is saved, and no model is called: compare
runs the mock, scripted.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from agent_policy import AGENTS, load
from helpdesk.assistant.agent import run_agent
from helpdesk.assistant.narrow import narrow_tools
from helpdesk.assistant.tools import Toolbox, triage_tools
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed
from helpdesk.kb import CHARS_PER_TOKEN
from helpdesk.model.anthropic_client import to_api, tool_to_api
from helpdesk.model.mock import MockModel
from helpdesk.model.types import ModelResponse, ToolCall, ToolSpec
from helpdesk.services import access
from helpdesk.services.access import Person
from helpdesk.services.errors import Invalid

SETS: dict[str, Callable[[sqlite3.Connection, Person], Toolbox]] = {
    "narrow": narrow_tools,
    "triage": triage_tools,
}


def definitions_size(specs: Sequence[ToolSpec]) -> int:
    """Characters of the tool definitions as the Anthropic adapter sends them, with every request."""
    return len(json.dumps([tool_to_api(spec) for spec in specs], ensure_ascii=False))


def tokens(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def parameters(spec: ToolSpec) -> str:
    required = spec.input_schema.get("required", [])
    names = [name if name in required else f"{name}?" for name in spec.input_schema.get("properties", {})]
    return f"{spec.name}({', '.join(names)})"


def run_list(toolbox: Toolbox, which: str) -> int:
    size = definitions_size(toolbox.specs)
    print(
        f"The {which} set: {len(toolbox.specs)} tools, whose definitions are {size:,} characters "
        f"(about {tokens(size):,} tokens) sent with every request.\n"
    )
    for spec in toolbox.specs:
        print(f"{parameters(spec)}{'  strict' if spec.strict else ''}")
        print(textwrap.fill(spec.description, 100, initial_indent="  ", subsequent_indent="  "))
        for name, rules in spec.input_schema.get("properties", {}).items():
            allowed = f" One of {', '.join(json.dumps(v) for v in rules['enum'])}." if "enum" in rules else ""
            print(
                textwrap.fill(
                    f"{name}: {rules.get('description', '')}{allowed}",
                    100,
                    initial_indent="    ",
                    subsequent_indent="      ",
                )
            )
        print()
    return 0


def run_schema(toolbox: Toolbox, name: str) -> int:
    found = [spec for spec in toolbox.specs if spec.name == name]
    if not found:
        known = ", ".join(spec.name for spec in toolbox.specs)
        print(f"No tool named {name!r}. The tools are: {known}.", file=sys.stderr)
        return 2
    print(json.dumps(tool_to_api(found[0]), indent=2, ensure_ascii=False))
    return 0


def argument_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def run_call(toolbox: Toolbox, person: Person, name: str, pairs: Sequence[str]) -> int:
    arguments = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            print(f"Write each argument as NAME=VALUE, such as ticket_id=4; got {pair!r}.", file=sys.stderr)
            return 2
        arguments[key] = argument_value(value)
    result = toolbox.run(ToolCall("call_1", name, arguments))
    print(f"{name} {json.dumps(arguments)}, acting for {person.label}")
    label = "error" if result.is_error else "result"
    for i, line in enumerate(result.content.splitlines()):
        print(f"{label + ':' if i == 0 else ' ' * (len(label) + 1)} {line}")
    return 1 if result.is_error else 0


# The comparison. Each task is run twice by the mock, once with each set, taking the fewest turns
# that set allows: every call that doesn't need an earlier call's result goes in the first turn,
# as a model may call several tools at once. Both runs end with the same answer, and a test checks
# that both runs' tool results hold the facts that answer needs, so the two runs are comparable.


@dataclass(frozen=True)
class Task:
    name: str
    prompt: str
    scripts: dict[str, list[ModelResponse]]
    facts: tuple[str, ...]  # what the tool results must contain for the answer to be supported


def calls(*pairs: tuple[str, dict[str, Any]], turn: int) -> ModelResponse:
    return ModelResponse(
        "tool_use",
        tool_calls=tuple(ToolCall(f"t{turn}_{i}", name, args) for i, (name, args) in enumerate(pairs, 1)),
    )


HISTORY_ANSWER = (
    "Hello Ben, and sorry for the confusion. Plan changes take effect at the next billing date, and until "
    "then you keep the features of your current plan, and you are billed for it [2#2]. You asked us in "
    "August whether you could downgrade mid-month, so this charge is for Pro up to that date."
)
NEXT_ANSWER = (
    "Start with ticket 1, Cannot reset my password: it is high priority and the oldest ticket you can "
    "see. Ticket 12, API token stopped working, is high priority too."
)
QUESTION = "billed for Pro after downgrading"

TASKS = [
    Task(
        "Ticket 2, with the customer's history",
        "Ticket 2: the customer says they were billed for Pro after downgrading. Check whether they have "
        "written in before, then draft a reply.",
        {
            "narrow": [
                calls(("get_ticket", {"ticket_id": 2}), ("search_kb", {"query": QUESTION}), turn=1),
                calls(
                    ("get_customer", {"customer_id": 2}),
                    ("list_customer_tickets", {"customer_id": 2}),
                    turn=2,
                ),
                ModelResponse("end_turn", text=HISTORY_ANSWER),
            ],
            "triage": [
                calls(("get_ticket", {"ticket_id": 2}), ("search_kb", {"query": QUESTION}), turn=1),
                ModelResponse("end_turn", text=HISTORY_ANSWER),
            ],
        },
        ("Ben Okafor", "billed for Pro", "Can I downgrade mid-month?", "closed", "2026-08-12", "[2#2]"),
    ),
    Task(
        "What to work on next",
        "What should I work on next?",
        {
            "narrow": [calls(("list_tickets", {}), turn=1), ModelResponse("end_turn", text=NEXT_ANSWER)],
            "triage": [calls(("find_tickets", {}), turn=1), ModelResponse("end_turn", text=NEXT_ANSWER)],
        },
        ("Cannot reset my password", "API token stopped working", "high"),
    ),
]


@dataclass(frozen=True)
class Measured:
    turns: int
    calls: int
    results: int  # characters of every tool result in the run
    sent: int  # characters of every request, as the Anthropic adapter would send them
    results_text: str


def measure(toolbox: Toolbox, system: str, task: Task, which: str) -> Measured:
    model = MockModel(task.scripts[which])
    run = run_agent(model, toolbox, system=system, task=task.prompt)
    sent = sum(
        len(
            json.dumps(
                {
                    "system": call.system,
                    "tools": [tool_to_api(t) for t in call.tools],
                    "messages": [to_api(m) for m in call.messages],
                },
                ensure_ascii=False,
            )
        )
        for call in model.calls
    )
    results = [r.content for m in run.transcript for r in m.tool_results]
    return Measured(
        turns=run.turns,
        calls=sum(len(m.tool_calls) for m in run.transcript),
        results=sum(len(r) for r in results),
        sent=sent,
        results_text="\n".join(results),
    )


def compare(conn: sqlite3.Connection, person: Person) -> dict[str, dict[str, Measured]]:
    system = load(AGENTS / "triage.toml")["system"]
    return {
        task.name: {which: measure(build(conn, person), system, task, which) for which, build in SETS.items()}
        for task in TASKS
    }


def run_compare(conn: sqlite3.Connection, person: Person) -> int:
    boxes = {which: build(conn, person) for which, build in SETS.items()}
    heads = {which: f"{which} ({len(box.specs)} tools)" for which, box in boxes.items()}
    width = 34
    print(f"Each task run by the mock, acting for {person.label}, in the fewest turns each set allows.")
    print("Characters are counted as the Anthropic adapter would send them; tokens are estimated at")
    print(f"{CHARS_PER_TOKEN} characters each.\n")
    print(" " * width + "".join(f"{heads[w]:>20}" for w in SETS))
    sizes = {w: definitions_size(box.specs) for w, box in boxes.items()}
    print(f"{'definitions, with every request':<{width}}" + "".join(f"{sizes[w]:>20,}" for w in SETS))
    for name, runs in compare(conn, person).items():
        print(f"\n{name}")
        rows = [
            ("  turns", lambda m: f"{m.turns}"),
            ("  tool calls", lambda m: f"{m.calls}"),
            ("  tool results, characters", lambda m: f"{m.results:,}"),
            ("  sent to the model, characters", lambda m: f"{m.sent:,}"),
            ("  sent to the model, tokens (est.)", lambda m: f"{tokens(m.sent):,}"),
        ]
        for label, show in rows:
            print(f"{label:<{width}}" + "".join(f"{show(runs[w]):>20}" for w in SETS))
    print("\nScripted runs show what each design costs on its shortest path. A real model may take more")
    print("turns with either set; measure that on a golden set of tasks (chapter 21).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.tools")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "schema", "call"):
        command = sub.add_parser(name)
        command.add_argument("--set", choices=list(SETS), default="triage", help="which tool set")
        if name == "schema":
            command.add_argument("tool")
        if name == "call":
            command.add_argument("tool")
            command.add_argument("arguments", nargs="*", help="NAME=VALUE pairs, such as ticket_id=4")
            command.add_argument("--max-result-chars", type=int, help="cut results longer than this")
        command.add_argument("--as", dest="person", default="sam", help="the member of staff to act for")
    compare_command = sub.add_parser("compare")
    compare_command.add_argument("--as", dest="person", default="sam", help="the member of staff to act for")
    args = parser.parse_args()

    conn = connect(":memory:")
    try:
        init_schema(conn)
        seed(conn)
        try:
            person = access.find_person(conn, args.person)
        except Invalid as e:
            print(e, file=sys.stderr)
            return 2
        if args.command == "compare":
            return run_compare(conn, person)
        toolbox = SETS[args.set](conn, person)
        if args.command == "list":
            return run_list(toolbox, args.set)
        if args.command == "schema":
            return run_schema(toolbox, args.tool)
        if args.max_result_chars is not None:
            toolbox = toolbox.limited(args.max_result_chars)
        return run_call(toolbox, person, args.tool, args.arguments)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
