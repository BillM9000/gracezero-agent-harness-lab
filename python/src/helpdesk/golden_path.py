"""Composition root for the golden path (chapter 29).

python -m helpdesk.golden_path new NAME --team TEAM --champion "..." --problem "..."
    writes agents/NAME.toml and usecases/NAME.toml from golden-path/, only once they pass
python -m helpdesk.golden_path check
    on every change: what the path writes passes the platform's checks from its first commit
python -m helpdesk.golden_path report
    team by team, which use cases are on the golden path, and the readiness exceptions in force
    (--today YYYY-MM-DD: as of that day)

The rules are in src/golden_path/rules.py and take no files. This module reads what they judge: the
templates, the platform's policy (chapter 18) and the readiness gate's evidence (chapter 28). Only
new writes anything. No model runs here.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from agent_policy import AGENTS, MODELS, POLICY, today
from agent_policy import load as load_toml
from agent_policy.rules import check as check_policy
from golden_path import AGENT_TEMPLATE, TEMPLATE, USE_CASE_TEMPLATE, load
from golden_path.rules import Answers, answer_problems, in_force, render, state
from helpdesk import readiness
from readiness import LIBRARY, READINESS, RUBRIC, USE_CASES
from readiness.rules import Result, review, score


@dataclass(frozen=True)
class Draft:
    """What the path would write for one set of answers, as text and as parsed."""

    agent_text: str
    use_case_text: str
    definition: dict[str, Any]
    record: dict[str, Any]


@dataclass(frozen=True)
class Verdict:
    results: list[Result]  # the readiness items, then the golden state as one line
    problems: list[str]  # anything that fails: the path promises it passes
    left: list[str]  # the items the path leaves to the team, as template.toml says


def draft(answers: Answers, template: Mapping[str, Any]) -> Draft:
    """Render the path for these answers. The tier is the rubric's for the path's intake answers."""
    scored, problems = score(template["intake"], load(RUBRIC))
    if scored is None:
        raise ValueError("golden-path/template.toml: [intake]: " + " ".join(problems))
    agent_text, use_case_text = render(
        answers,
        template,
        scored.tier,
        AGENT_TEMPLATE.read_text(encoding="utf-8"),
        USE_CASE_TEMPLATE.read_text(encoding="utf-8"),
    )
    return Draft(agent_text, use_case_text, tomllib.loads(agent_text), tomllib.loads(use_case_text))


def verify(d: Draft, template: Mapping[str, Any], on: date) -> Verdict:
    """Everything the platform checks of a use case, run on the draft with the lab's real evidence,
    as if its two files were already in agents/ and usecases/."""
    name = d.definition["name"]
    reasons = [v.reason for v in check_policy(d.definition, load_toml(POLICY), load_toml(MODELS), on)]
    found = readiness.evidence(on)
    found = dataclasses.replace(
        found,
        definitions={**found.definitions, name: d.definition},
        policy={**found.policy, name: reasons},
    )
    library = frozenset(c["name"] for c in load(LIBRARY)["capabilities"])
    r = review(d.record, load(RUBRIC), load(READINESS), library, found)
    problems = [f"usecases/{name}.toml: {p}" for p in r.problems]
    leaves = template["promise"]["leaves"]
    problems += [f"{res.item}: {res.detail}" for res in r.results if not res.ok and res.item not in leaves]
    golden = state(d.record, d.definition, template, library, on)
    problems += [f"golden state: {res.item}: {res.detail}" for res in golden if not res.ok]
    names = ", ".join(res.item for res in golden)
    on_path = Result("golden state", all(res.ok for res in golden), f"on the golden path: {names}")
    left = [res.item for res in r.results if not res.ok and res.item in leaves]
    return Verdict([*r.results, on_path], problems, left)


def show(verdict: Verdict) -> list[str]:
    width = max(len(res.item) for res in verdict.results)
    return [f"  {'ok' if res.ok else 'left':<5} {res.item:<{width}}  {res.detail}" for res in verdict.results]


def example(template: Mapping[str, Any]) -> Answers:
    e = template["example"]
    return Answers(e["name"], e["team"], e["champion"], e["problem"])


def check(on: date | None = None) -> int:
    on = on or today()
    template = load(TEMPLATE)
    try:
        d = draft(example(template), template)
    except (KeyError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"The golden path doesn't render: {error!r}")
        return 1
    verdict = verify(d, template, on)
    version = template["version"]
    print(f"The golden path (golden-path/template.toml, version {version}), for {d.definition['name']}:")
    print("\n".join(show(verdict)))
    if verdict.problems:
        print(f"\n{len(verdict.problems)} problem(s): a use case started on the path would fail them.")
        print("\n".join(f"  {p}" for p in verdict.problems))
        return 1
    print(
        "\nStarted on the path, a use case passes every other item from its first commit. "
        f"Left for the team, as the path says: {', '.join(verdict.left)}."
    )
    return 0


def taken() -> set[str]:
    return {p.stem for p in [*AGENTS.glob("*.toml"), *USE_CASES.glob("*.toml")]}


def new(answers: Answers, on: date | None = None) -> int:
    on = on or today()
    template = load(TEMPLATE)
    problems = answer_problems(answers, load_toml(POLICY)["teams"], taken())
    if problems:
        print("\n".join(problems))
        print("Nothing was written.")
        return 1
    d = draft(answers, template)
    verdict = verify(d, template, on)
    if verdict.problems:
        print("\n".join(verdict.problems))
        print("Nothing was written: the golden path itself fails (python -m helpdesk.golden_path check).")
        return 1
    agent, use_case = AGENTS / f"{answers.name}.toml", USE_CASES / f"{answers.name}.toml"
    agent.write_text(d.agent_text, encoding="utf-8")
    use_case.write_text(d.use_case_text, encoding="utf-8")
    print(
        f"Wrote agents/{agent.name} and usecases/{use_case.name} from the golden path "
        f"(version {template['version']})."
    )
    print("\n".join(show(verdict)))
    print(
        f"Left before production: {', '.join(verdict.left)}. Rewrite the first paragraph of its system "
        "prompt for the job, then give it golden sets and ask for a promotion and a sign-off."
    )
    return 0


def report(on: date | None = None) -> int:
    on = on or today()
    template = load(TEMPLATE)
    library = frozenset(c["name"] for c in load(LIBRARY)["capabilities"])
    definitions = readiness.definitions()
    names = ", ".join(s["id"] for s in template["state"])
    print(f"The golden state (golden-path/template.toml, version {template['version']}): {names}.\n")
    teams: dict[str, list[tuple[str, str, str, str]]] = {}
    off: dict[str, int] = {s["id"]: 0 for s in template["state"]}
    excused: list[tuple[str, Mapping[str, Any]]] = []
    for path in readiness.use_cases():
        record = load(path)
        name, stage = str(record.get("name", path.stem)), str(record.get("stage", "?"))
        excused += [(name, e) for e in in_force(record, on)]
        if stage == "proposed":
            teams.setdefault(str(record.get("team")), []).append(("proposed", name, "", ""))
            continue
        results = state(record, definitions.get(record.get("agent", "")), template, library, on)
        failing = [res for res in results if not res.ok]
        for res in failing:
            off[res.item] += 1
        why = "; ".join(f"{res.item}: {res.detail}" for res in failing)
        teams.setdefault(str(record.get("team")), []).append(("off" if failing else "on", name, stage, why))
    for team, rows in sorted(teams.items()):
        built = [row for row in rows if row[0] != "proposed"]
        on_path = sum(1 for row in built if row[0] == "on")
        proposed = len(rows) - len(built)
        more = f", and {proposed} proposed" if proposed else ""
        print(f"{team}: {on_path} of {len(built)} use case(s) on the golden path{more}")
        print("\n".join(line(rows)))
        print()
    print("Off the path, by check: " + ", ".join(f"{check} {n}" for check, n in off.items()) + ".")
    print(exceptions(excused, on))
    return 0


def line(rows: Sequence[tuple[str, str, str, str]]) -> list[str]:
    w0, w1, w2 = (max(len(row[i]) for row in rows) for i in range(3))
    return [f"  {a:<{w0}}  {b:<{w1}}  {c:<{w2}}  {d}".rstrip() for a, b, c, d in rows]


def exceptions(excused: Sequence[tuple[str, Mapping[str, Any]]], on: date) -> str:
    if not excused:
        return f"Readiness exceptions in force on {on}: none."
    counts: dict[str, int] = {}
    for _, e in excused:
        counts[e["item"]] = counts.get(e["item"], 0) + 1
    head = ", ".join(f"{item} {n}" for item, n in sorted(counts.items()))
    rows = [f"  {name}: {e['item']}, by {e['by']} until {e['until']}: {e['reason']}" for name, e in excused]
    return "\n".join([f"Readiness exceptions in force on {on}, by item: {head}.", *rows])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helpdesk.golden_path", description=__doc__.split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    started = commands.add_parser("new", help="start a use case on the golden path")
    started.add_argument("name", help="3 to 40 lowercase letters, digits and hyphens")
    started.add_argument("--team", required=True, help="a team in agents/policy.toml")
    started.add_argument("--champion", required=True, help="the person on the team who answers for it")
    started.add_argument("--problem", required=True, help="what it's for, in one sentence")
    commands.add_parser("check", help="what the path writes passes the platform's checks")
    reported = commands.add_parser("report", help="which use cases are on the golden path")
    reported.add_argument("--today", type=date.fromisoformat, help="as of YYYY-MM-DD")
    args = parser.parse_args(argv)
    if args.command == "new":
        return new(Answers(args.name, args.team, args.champion, args.problem))
    if args.command == "check":
        return check()
    return report(args.today)


if __name__ == "__main__":
    sys.exit(main())
