"""The central team's rules for a use case (chapter 28), as pure functions.

score(intake, rubric) turns the intake answers into a tier. review(record, ...) checks one use case
against the readiness checklist for its tier, with the evidence the caller gathered: the agent
definitions and what the platform's policy says of each, the last promotion, the catalog's servers
and the teams. It reads no files and calls nothing, so the tests can pin exactly what it accepts.
Only a use case in production must pass every item; for the rest, the items not yet met are what's
left to do. excused(...) applies a reviewer's exceptions (chapter 29): an item may wait until a set
day, with a reason, and an exception that has nothing left to excuse fails.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

STAGES = ("proposed", "building", "production")

# Every field a use case has, its type, and why the central team needs it.
FIELDS: dict[str, tuple[type, str]] = {
    "name": (str, "Name the use case, so its reviews and costs can be told apart."),
    "team": (str, "Name the team that builds it and pays for its model calls."),
    "champion": (str, "Name the person on that team who answers for it."),
    "problem": (str, "Say what it's for, in a sentence the people who'll use it would recognize."),
    "stage": (str, f"Say how far it has got: one of {', '.join(STAGES)}."),
    "needs": (list, "List what it builds on from the capability library."),
    "intake": (dict, "Answer the intake questions in usecases/rubric.toml."),
}
OPTIONAL: dict[str, tuple[type, str]] = {
    "agent": (str, "Name its agent definition in agents/."),
    "servers": (list, "List the MCP servers it uses, from catalog/servers.toml."),
    "tier": (str, "Record the tier its triage gave."),
    "signoffs": (list, "Record each reviewer's sign-off."),
    "exceptions": (list, "Record each reviewer's exception: the item, the reason and the day it ends."),
}
SIGNOFF_FIELDS = ("role", "by", "on", "fingerprint")
EXCEPTION_FIELDS = ("item", "reason", "by", "on", "until")
# What a reviewer signs off leaves these out: where it has got to, and the reviewers' own records.
NOT_REVIEWED = ("stage", "signoffs", "exceptions")
TYPE_NAMES = {str: "text", list: "a list", dict: "a table"}


def fingerprint(record: Mapping[str, Any], definition: Mapping[str, Any] | None) -> str:
    """What a reviewer signs off: the use case, apart from its stage, sign-offs and exceptions, and its
    agent's definition. Parsed first, so a comment or a blank line changes nothing; any other change
    to either needs a new sign-off."""
    reviewed = {k: v for k, v in record.items() if k not in NOT_REVIEWED}
    text = json.dumps({"use case": reviewed, "agent": definition}, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Scored:
    score: int
    tier: str
    parts: tuple[tuple[str, str, int], ...]  # (question, answer, points)

    def line(self) -> str:
        return ", ".join(f"{q} {a} {p}" for q, a, p in self.parts) + f": {self.score}, {self.tier}"


def tier_of(total: int, rubric: Mapping[str, Any]) -> str:
    """The highest tier whose lowest score the total reaches."""
    tiers: Mapping[str, int] = rubric["tiers"]
    reached = [name for name, lowest in tiers.items() if total >= lowest]
    return reached[-1] if reached else next(iter(tiers))


def score(intake: Mapping[str, Any], rubric: Mapping[str, Any]) -> tuple[Scored | None, list[str]]:
    """The intake answers' points, total and tier, or None and what's wrong with the answers."""
    questions: Mapping[str, Any] = rubric["questions"]
    problems = [
        f"intake.{q}: isn't a question in usecases/rubric.toml." for q in intake if q not in questions
    ]
    parts = []
    for question, spec in questions.items():
        answers: Mapping[str, int] = spec["answers"]
        answer = intake.get(question)
        if answer is None:
            problems.append(f"intake.{question}: missing. {spec['ask']} One of {', '.join(answers)}.")
        elif answer not in answers:
            problems.append(
                f"intake.{question}: {json.dumps(answer)} isn't an answer. Use one of {', '.join(answers)}."
            )
        else:
            parts.append((question, answer, answers[answer]))
    if problems:
        return None, problems
    total = sum(points for _, _, points in parts)
    return Scored(total, tier_of(total, rubric), tuple(parts)), []


def floors(definition: Mapping[str, Any] | None, rubric: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """What the agent's tools prove about the answers: for each question, the least answer it may
    take and the tool that sets it."""
    found: dict[str, tuple[str, str]] = {}
    if definition is None:
        return found
    for tool in definition.get("tools", []):
        for question, least in rubric.get("floors", {}).get(tool, {}).items():
            points = rubric["questions"][question]["answers"]
            if question not in found or points[least] > points[found[question][0]]:
                found[question] = (least, tool)
    return found


@dataclass(frozen=True)
class Promotion:
    """The last promotion (chapter 23), as the caller read it."""

    promoted: str
    measured_on: str
    agents: frozenset[str]  # the agent definitions it fingerprinted
    current: bool  # nothing it fingerprinted has changed since
    trials: int
    injections: Mapping[str, int]  # red-team case: trials passed


@dataclass(frozen=True)
class Evidence:
    definitions: Mapping[str, Mapping[str, Any]]  # agent name: its definition
    policy: Mapping[str, Sequence[str]]  # agent name: the platform policy's reasons, empty if it passes
    promotion: Promotion | None
    servers: frozenset[str]  # the catalog's approved MCP servers
    teams: frozenset[str]  # the teams in agents/policy.toml
    today: date  # the day exceptions are judged on


@dataclass(frozen=True)
class Result:
    item: str
    ok: bool
    detail: str
    excused: bool = False  # ok only because a reviewer's exception is in force


@dataclass
class Review:
    name: str
    stage: str
    tier: str | None  # recorded, or else what the rubric gives
    recorded: bool
    scored: Scored | None
    problems: list[str] = field(default_factory=list)  # a malformed record, at any stage
    results: list[Result] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.problems and all(r.ok for r in self.results)

    @property
    def passes(self) -> bool:
        """A use case passes the check when its record is sound and, in production, it's ready."""
        return not self.problems and (self.stage != "production" or self.ready)


@dataclass(frozen=True)
class Context:
    record: Mapping[str, Any]
    rubric: Mapping[str, Any]
    readiness: Mapping[str, Any]
    library: frozenset[str]
    evidence: Evidence
    scored: Scored | None
    tier: str | None

    @property
    def agent(self) -> str | None:
        return self.record.get("agent")

    @property
    def definition(self) -> Mapping[str, Any] | None:
        return self.evidence.definitions.get(self.agent) if self.agent else None


def triaged(c: Context) -> tuple[bool, str]:
    if c.scored is None:
        return False, "the intake answers can't be scored"
    for question, (least, tool) in floors(c.definition, c.rubric).items():
        points = c.rubric["questions"][question]["answers"]
        said = c.record["intake"][question]
        if points[said] < points[least]:
            return False, (
                f"intake.{question} says {said}, but agents/{c.agent}.toml gives it {tool}, so it's at "
                f"least {least}. Answer for what it can do, then triage it again."
            )
    recorded = c.record.get("tier")
    if recorded is None:
        return False, f"not triaged yet: the rubric gives {c.scored.line()}"
    if recorded != c.scored.tier:
        return False, (
            f"records {recorded}, but its answers score {c.scored.line()}. The tier sets what the gate "
            "asks for: record the rubric's."
        )
    return True, c.scored.line()


def library(c: Context) -> tuple[bool, str]:
    missing = [need for need in c.record["needs"] if need not in c.library]
    if missing:
        return False, (
            f"{', '.join(map(json.dumps, missing))} isn't in the library: the platform team decides "
            "whether to build it, for everyone"
        )
    return True, f"{len(c.record['needs'])} needs, all in the library"


def policy(c: Context) -> tuple[bool, str]:
    if c.agent is None:
        return False, "no agent definition yet"
    if c.agent not in c.evidence.definitions:
        return False, f"agents/{c.agent}.toml doesn't exist"
    reasons = c.evidence.policy.get(c.agent, ())
    if reasons:
        more = f" (and {len(reasons) - 1} more)" if len(reasons) > 1 else ""
        return False, f"agents/{c.agent}.toml breaks the platform's policy: {reasons[0]}{more}"
    return True, f"agents/{c.agent}.toml passes the platform's policy"


def servers(c: Context) -> tuple[bool, str]:
    wanted = c.record.get("servers", [])
    unknown = [s for s in wanted if s not in c.evidence.servers]
    if unknown:
        return False, f"{', '.join(map(json.dumps, unknown))} isn't in catalog/servers.toml (chapter 13)"
    return True, f"{', '.join(wanted)}, in the catalog" if wanted else "uses none"


def promotion(c: Context) -> tuple[bool, str]:
    p = c.evidence.promotion
    if p is None:
        return False, "nothing has been promoted (python -m helpdesk.gate run --promote)"
    if c.agent is None or c.agent not in p.agents:
        who = f"agents/{c.agent}.toml" if c.agent else "its agent"
        return (
            False,
            f"{who} isn't in the promotion of {p.promoted}: its golden sets and a promotion come first",
        )
    if not p.current:
        return False, (
            f"something the promotion of {p.promoted} measured has changed since: "
            "python -m helpdesk.gate check"
        )
    return True, f"in the promotion of {p.promoted}, measured on {p.measured_on}, and unchanged since"


def red_team(c: Context) -> tuple[bool, str]:
    p = c.evidence.promotion
    if p is None or c.agent not in p.agents:
        return False, "no promotion of its agent to read the red-team suite from"
    if not p.injections:
        return False, f"the promotion of {p.promoted} didn't run the red-team suite"
    failed = [case for case, passed in p.injections.items() if passed < p.trials]
    if failed:
        return False, f"{len(failed)} of {len(p.injections)} red-team cases failed a trial at the promotion"
    return True, f"all {len(p.injections)} red-team cases passed {p.trials} of {p.trials} trials"


def sign_off(c: Context) -> tuple[bool, str]:
    roles: Sequence[str] = c.readiness["signoffs"][c.tier] if c.tier else ()
    now = fingerprint(c.record, c.definition)
    given = c.record.get("signoffs", [])
    done = []
    for role in roles:
        theirs = [s for s in given if s.get("role") == role]
        if not theirs:
            return False, f"needs a {role} reviewer's sign-off"
        s = theirs[-1]
        if s["by"] not in c.readiness["reviewers"].get(role, []):
            return False, f"{s['by']} isn't a {role} reviewer in usecases/readiness.toml"
        if s["by"] == c.record["champion"]:
            return False, f"{s['by']} is its champion, and can't sign off their own use case"
        if s["fingerprint"] != now:
            return False, (
                f"{role}'s sign-off by {s['by']} on {s['on']} was for something else: the use case or its "
                "agent changed since. Ask for a new one (python -m helpdesk.readiness fingerprint FILE)."
            )
        done.append(f"{role}: {s['by']}, {s['on']}")
    return True, "; ".join(done) if done else "none needed"


# Every item of usecases/readiness.toml, and the check behind it. A test keeps the two in step.
CHECKS: dict[str, Callable[[Context], tuple[bool, str]]] = {
    "triaged": triaged,
    "library": library,
    "policy": policy,
    "servers": servers,
    "promotion": promotion,
    "red-team": red_team,
    "sign-off": sign_off,
}


def shape(record: Mapping[str, Any], rubric: Mapping[str, Any], evidence: Evidence) -> list[str]:
    """What's wrong with the record itself, whatever its stage."""
    problems = []
    known = {**FIELDS, **OPTIONAL}
    for key in record:
        if key not in known:
            problems.append(f"{key}: isn't a field of a use case. The fields are {', '.join(known)}.")
    for key, (kind, why) in known.items():
        if key not in record:
            if key in FIELDS:
                problems.append(f"{key}: missing. {why}")
        elif not isinstance(record[key], kind):
            problems.append(f"{key}: must be {TYPE_NAMES[kind]}. {why}")
    if problems:
        return problems
    if record["stage"] not in STAGES:
        problems.append(
            f"stage: {json.dumps(record['stage'])} isn't a stage. Use one of {', '.join(STAGES)}."
        )
    if record["team"] not in evidence.teams:
        problems.append(
            f"team: {json.dumps(record['team'])} isn't a team in agents/policy.toml, so nothing would limit "
            "what it spends (chapter 27). A new team needs a monthly budget there first."
        )
    tier = record.get("tier")
    if tier is not None and tier not in rubric["tiers"]:
        problems.append(f"tier: {json.dumps(tier)} isn't a tier. Use one of {', '.join(rubric['tiers'])}.")
    if tier is None and record["stage"] != "proposed":
        problems.append("tier: missing. A use case past proposed records the tier its triage gave.")
    if record.get("agent") is None and record["stage"] == "production":
        problems.append("agent: missing. A use case in production names its agent definition.")
    for i, s in enumerate(record.get("signoffs", [])):
        lacking = [f for f in SIGNOFF_FIELDS if not isinstance(s, dict) or f not in s]
        if lacking:
            problems.append(f"signoffs[{i}]: needs {', '.join(lacking)}.")
    return problems


def exception_problems(record: Mapping[str, Any], readiness: Mapping[str, Any], today: date) -> list[str]:
    """What's wrong with the exceptions a use case records (chapter 29), whatever its stage. An
    exception names an item that may take one, gives a reason, comes from a reviewer who isn't the
    champion, was given on or before today, and ends within the checklist's limit of the day it was
    given, so never more than that limit from today. A day given in the future would stretch it:
    given "on" 2027-01-01 until 2027-01-20, it would excuse the item from now until then."""
    rules = readiness["exceptions"]
    reviewers = {name for names in readiness["reviewers"].values() for name in names}
    problems = []
    for i, e in enumerate(record.get("exceptions", [])):
        where = f"exceptions[{i}]"
        lacking = [f for f in EXCEPTION_FIELDS if not isinstance(e, dict) or f not in e]
        if lacking:
            problems.append(f"{where}: needs {', '.join(lacking)}.")
            continue
        if e["item"] not in rules["items"]:
            problems.append(
                f"{where}: {json.dumps(e['item'])} can't be excused; only {', '.join(rules['items'])} can. "
                "Meet it, or ask for the rule itself to change, for everyone."
            )
        if not str(e["reason"]).strip():
            problems.append(f"{where}: reason is empty. Say why it can wait, so nobody has to guess later.")
        if e["by"] not in reviewers:
            problems.append(f"{where}: {e['by']} isn't a reviewer in usecases/readiness.toml.")
        elif e["by"] == record["champion"]:
            problems.append(f"{where}: {e['by']} is its champion, and can't excuse their own use case.")
        if not (isinstance(e["on"], date) and isinstance(e["until"], date)):
            problems.append(f"{where}: on and until must be dates, such as 2026-09-25.")
        elif e["on"] > today:
            problems.append(
                f"{where}: is given on {e['on']}, after today ({today}). An exception counts from the "
                "day it's given: record it on that day, not before."
            )
        # With on no later than today, this also keeps until within max_days of today.
        elif not 0 < (e["until"] - e["on"]).days <= rules["max_days"]:
            problems.append(
                f"{where}: runs from {e['on']} to {e['until']}. An exception ends within "
                f"{rules['max_days']} days of the day it's given; for longer, change the rule instead."
            )
    return problems


def excused(record: Mapping[str, Any], results: list[Result], today: date) -> tuple[list[Result], list[str]]:
    """The results with the use case's exceptions applied, and the exceptions with nothing left to
    excuse. An item that fails is excused while its exception is in force, and fails again, saying
    so, the day after it ends; the latest exception for an item is the one that counts."""
    given = {e["item"]: (i, e) for i, e in enumerate(record.get("exceptions", []))}
    out: list[Result] = []
    stale: list[str] = []
    for r in results:
        if r.item not in given:
            out.append(r)
            continue
        i, e = given[r.item]
        if r.ok:
            stale.append(f"exceptions[{i}]: {r.item} passes now, so there's nothing to excuse. Remove it.")
            out.append(r)
        elif today > e["until"]:
            out.append(Result(r.item, False, f"its exception ended on {e['until']}: {r.detail}"))
        else:
            detail = f"by {e['by']} until {e['until']}: {e['reason']} Without it: {r.detail}"
            out.append(Result(r.item, True, detail, excused=True))
    asked = {r.item for r in results}
    for item, (i, _) in given.items():
        if item not in asked:
            stale.append(f"exceptions[{i}]: its tier doesn't ask for {item}, so there's nothing to excuse.")
    return out, stale


def review(
    record: Mapping[str, Any],
    rubric: Mapping[str, Any],
    readiness: Mapping[str, Any],
    library_names: frozenset[str],
    evidence: Evidence,
) -> Review:
    name = str(record.get("name", "?"))
    stage = str(record.get("stage", "?"))
    problems = shape(record, rubric, evidence)
    problems += [] if problems else exception_problems(record, readiness, evidence.today)
    scored, wrong = (None, []) if problems else score(record["intake"], rubric)
    problems += wrong
    if problems:
        return Review(name, stage, record.get("tier"), "tier" in record, None, problems)
    tier = record.get("tier") or (scored.tier if scored else None)
    context = Context(record, rubric, readiness, library_names, evidence, scored, tier)
    results = [
        Result(item["id"], *CHECKS[item["id"]](context))
        for item in readiness["items"]
        if tier in item["tiers"]
    ]
    results, stale = excused(record, results, evidence.today)
    return Review(name, stage, tier, "tier" in record, scored, stale, results)
