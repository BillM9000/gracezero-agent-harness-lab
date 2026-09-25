"""Composition root for the central team's intake and readiness gate (chapter 28).

python -m helpdesk.readiness check              every use case in usecases/ against its tier's items
                                                (--today YYYY-MM-DD: judge exceptions as of that day)
python -m helpdesk.readiness triage FILE        one use case's intake answers: score, tier, path
python -m helpdesk.readiness fingerprint FILE   what a reviewer signs off for that use case

The rules are in src/readiness/rules.py and take no files; this module gathers what they judge:
the agent definitions and what the platform's policy says of each (chapter 18), the last promotion
and whether anything it measured has changed (chapter 23), the catalog's MCP servers (chapter 13)
and the teams with budgets (chapter 27). It also checks that every capability in the library names
a module that exists. A reviewer's exception excuses an item until a set day (chapter 29). No model
runs here.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import tomllib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from agent_policy import AGENTS, MODELS, NOT_DEFINITIONS, POLICY, today
from agent_policy import load as load_toml
from agent_policy.rules import check as check_policy
from helpdesk import gate
from mcp_governance import SERVERS
from readiness import LIBRARY, NOT_USE_CASES, READINESS, RUBRIC, USE_CASES, load
from readiness.rules import CHECKS, Evidence, Promotion, Result, Review, fingerprint, review, score

# The promotion record's configuration names each agent definition it fingerprinted this way.
FINGERPRINTED = re.compile(r"^agents/([\w-]+)\.toml:")


def shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(USE_CASES.parent).as_posix()
    except ValueError:
        return path.as_posix()


def definitions() -> dict[str, dict[str, Any]]:
    found = {}
    for path in sorted(AGENTS.glob("*.toml")):
        if path.name not in NOT_DEFINITIONS:
            definition = load_toml(path)
            found[str(definition.get("name", path.stem))] = definition
    return found


def promotion() -> Promotion | None:
    record = gate.load_record()
    if record is None:
        return None
    was: Mapping[str, str] = record["configuration"]
    agents = frozenset(m.group(1) for name in was if (m := FINGERPRINTED.match(name)))
    return Promotion(
        promoted=record["promoted"],
        measured_on=record["measured_on"],
        agents=agents,
        current=gate.configuration() == dict(was),
        trials=int(record["trials"]),
        injections=dict(record["suites"].get("injections", {})),
    )


def evidence(on: date | None = None) -> Evidence:
    """What the rules judge, as of a day: today unless one is given."""
    policy, models = load_toml(POLICY), load_toml(MODELS)
    on = on or today()
    found = definitions()
    return Evidence(
        definitions=found,
        policy={name: [v.reason for v in check_policy(d, policy, models, on)] for name, d in found.items()},
        promotion=promotion(),
        servers=frozenset(s["name"] for s in load_toml(SERVERS).get("servers", [])),
        teams=frozenset(policy["teams"]),
        today=on,
    )


def library_problems(library: Mapping[str, Any]) -> list[str]:
    problems = []
    for entry in library["capabilities"]:
        if importlib.util.find_spec(entry["provided_by"]) is None:
            problems.append(
                f"usecases/library.toml: {entry['name']}: provided_by {entry['provided_by']} isn't a module "
                "here. The library lists only what the platform has."
            )
    return problems


def checklist_problems(readiness: Mapping[str, Any]) -> list[str]:
    ids = [item["id"] for item in readiness["items"]]
    problems = [
        f"usecases/readiness.toml: {i}: no check in src/readiness/rules.py." for i in ids if i not in CHECKS
    ]
    problems += [
        f"src/readiness/rules.py: {c}: not an item in usecases/readiness.toml."
        for c in CHECKS
        if c not in ids
    ]
    return problems


def use_cases() -> list[Path]:
    return sorted(p for p in USE_CASES.glob("*.toml") if p.name not in NOT_USE_CASES)


def status(res: Result) -> str:
    return "excused" if res.excused else "ok" if res.ok else "left"


def describe(r: Review, record: Mapping[str, Any]) -> list[str]:
    if r.problems:
        head = [f"{r.name}: {r.stage}, with {len(r.problems)} problem(s) in the record:"]
        return head + [f"  {p}" for p in r.problems] + results(r)
    if r.scored is None or not r.recorded:
        tier = f"not triaged yet (the rubric gives {r.tier})"
    elif r.scored.tier != r.tier:
        tier = f"recorded {r.tier}, though its answers score {r.scored.score}, {r.scored.tier}"
    else:
        tier = f"{r.tier} (score {r.scored.score})"
    return [f"{r.name}: {r.stage}, {tier}, {record['team']}, champion {record['champion']}"] + results(r)


def results(r: Review) -> list[str]:
    if not r.results:
        return []
    width = max(len(res.item) for res in r.results)
    label = max(5, *(len(status(res)) + 1 for res in r.results))
    return [f"  {status(res):<{label}} {res.item:<{width}}  {res.detail}" for res in r.results]


def check(on: date | None = None) -> int:
    rubric, readiness, library = load(RUBRIC), load(READINESS), load(LIBRARY)
    problems = library_problems(library) + checklist_problems(readiness)
    names = frozenset(entry["name"] for entry in library["capabilities"])
    found = evidence(on)
    print(f"The capability library (usecases/library.toml): {len(names)} capabilities.")
    print(f"The readiness checklist (usecases/readiness.toml): {len(readiness['items'])} items.\n")
    reviews = []
    for path in use_cases():
        try:
            record = load(path)
        except tomllib.TOMLDecodeError as error:
            problems.append(f"{shown(path)}: isn't valid TOML: {error}")
            continue
        r = review(record, rubric, readiness, names, found)
        reviews.append(r)
        print("\n".join(describe(r, record)) + "\n")
        if not r.passes:
            reason = "its record has problems" if r.problems else "it's in production and not ready"
            problems.append(f"{shown(path)}: {reason}.")
    live = [r for r in reviews if r.stage == "production"]
    left = sum(1 for r in reviews if r.stage != "production" for res in r.results if not res.ok)
    if problems:
        print(f"{len(problems)} problem(s):")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    others = len(reviews) - len(live)
    print(
        f"{len(live)} use case(s) in production, each passing every item its tier needs. "
        f"{others} more on the way, with {left} item(s) left between them."
    )
    return 0


def triage(path: Path) -> int:
    rubric, library = load(RUBRIC), load(LIBRARY)
    record = load(path)
    scored, problems = score(record.get("intake", {}), rubric)
    if scored is None:
        print("\n".join(f"{shown(path)}: {p}" for p in problems))
        return 1
    print(f"{record.get('name', path.stem)}: {record.get('problem', '')}")
    for question, answer, points in scored.parts:
        print(f"  {question:<9} {answer:<10} {points}   {rubric['questions'][question]['ask']}")
    print(f"  Score {scored.score}: {scored.tier}. {rubric['paths'][scored.tier]}")
    readiness = load(READINESS)
    items = [item["id"] for item in readiness["items"] if scored.tier in item["tiers"]]
    print(f"  Before production: {', '.join(items)}.")
    names = {entry["name"] for entry in library["capabilities"]}
    missing = [need for need in record.get("needs", []) if need not in names]
    if missing:
        print(f"  Not in the library: {', '.join(missing)}. The platform team decides whether to build it.")
    if record.get("tier") not in (None, scored.tier):
        print(f"  It records {record['tier']}: change tier to {scored.tier}.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helpdesk.readiness", description=__doc__.split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    checked = commands.add_parser("check", help="every use case against the items its tier needs")
    checked.add_argument("--today", type=date.fromisoformat, help="judge exceptions as of YYYY-MM-DD")
    triaged = commands.add_parser("triage", help="score one use case's intake answers")
    triaged.add_argument("file", type=Path)
    printed = commands.add_parser("fingerprint", help="what a reviewer signs off for one use case")
    printed.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "check":
        return check(args.today)
    try:
        if args.command == "triage":
            return triage(args.file)
        record = load(args.file)
        agent = record.get("agent")
        print(fingerprint(record, definitions().get(agent) if agent else None))
        return 0
    except (OSError, tomllib.TOMLDecodeError) as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
