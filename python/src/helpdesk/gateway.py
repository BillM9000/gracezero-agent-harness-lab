"""Composition root for the model gateway (chapter 27).

python -m helpdesk.gateway check        the lab's gateway and the demo's, with no model: every team
                                        has a budget and limits, and every route's models are
                                        approved, tracked, not retiring and deployed somewhere
python -m helpdesk.gateway demo         a made-up organization (gateway/demo.toml) through the lab's
                                        gateway, with a stand-in provider and a clock moved by hand
python -m helpdesk.gateway report FILE  a gateway record's cost and outcomes, by team and route

Every command in the lab that calls a real model (--real) gets its client here, from the lab's
gateway: the teams in agents/policy.toml, one route per agent definition with the model the
definition names, and Anthropic's API as the one deployment of each approved model. Only this module
builds a provider's client; tests/fitness/test_one_door_to_the_provider.py fails the build if
anything else does. The record goes to records/gateway.jsonl, or where HELPDESK_GATEWAY_RECORD says.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from agent_policy import AGENTS, MODELS, NOT_DEFINITIONS, POLICY, load, today
from agent_policy.rules import lifecycle
from helpdesk.kb import CHARS_PER_TOKEN
from helpdesk.model.budget import request_chars
from helpdesk.model.calls import Call, CallLog, read
from helpdesk.model.gateway import Connect, Deployment, Gateway, NothingAnswered, Refused, Route, Team, money
from helpdesk.model.types import Message, ModelClient, ModelResponse, ToolSpec, Unavailable, Usage

PYTHON = Path(__file__).resolve().parents[2]
LAB = PYTHON.parent
DEMO = PYTHON / "gateway" / "demo.toml"
RECORD_VARIABLE = "HELPDESK_GATEWAY_RECORD"


def record_path() -> Path:
    fixed = os.environ.get(RECORD_VARIABLE)
    return Path(fixed) if fixed else LAB / "records" / "gateway.jsonl"


# --- The lab's gateway.


def teams_of(data: Mapping[str, Any]) -> list[Team]:
    return [
        Team(name, float(t["monthly_usd"]), int(t["requests_per_minute"]), int(t["input_tokens_per_minute"]))
        for name, t in data["teams"].items()
    ]


def definitions() -> list[dict[str, Any]]:
    return [load(path) for path in sorted(AGENTS.glob("*.toml")) if path.name not in NOT_DEFINITIONS]


def anthropic(client: Any = None) -> Connect:
    """Anthropic's API, the lab's one provider. Tests pass a fake client; without one, the SDK
    looks for a credential, and every call is billed."""

    def connect(deployment: Deployment, max_tokens: int) -> ModelClient:
        from helpdesk.model.anthropic_client import AnthropicModel

        return AnthropicModel(client, model=deployment.model, max_tokens=max_tokens)

    return connect


def lab_gateway(connect: Connect | None = None, record: Path | None = None) -> Gateway:
    """Each agent's route is the one model its definition names, the model its golden sets and the
    gate measured (chapter 23). Changing it is a change to the definition, which the gate sees."""
    policy = load(POLICY)
    routes = [Route(d["name"], (d["model"],)) for d in definitions()]
    deployments = [Deployment("anthropic", model) for model in policy["models"]]
    log = CallLog(record or record_path(), "gateway")
    return Gateway(
        teams_of(policy), routes, deployments, connect or anthropic(), log, chars_per_token=CHARS_PER_TOKEN
    )


_GATEWAYS: dict[int, Gateway] = {}  # one for the command's real calls, and one per test's fake client


def for_agent(definition: Mapping[str, Any], client: Any = None) -> ModelClient:
    """A client for an agent's calls through the lab's gateway: its owner pays and its name is the
    route. One gateway serves every call a command makes, so its limits and budget see them all."""
    key = id(client) if client is not None else 0
    if key not in _GATEWAYS:
        _GATEWAYS[key] = lab_gateway(anthropic(client))
    gateway = _GATEWAYS[key]
    route = gateway.routes.get(definition["name"])
    if route is not None and definition["model"] not in route.models:
        raise ValueError(
            f"{definition['name']} names {definition['model']}, which isn't on its route "
            f"({', '.join(route.models)}). The route comes from agents/{definition['name']}.toml: "
            "change it there."
        )
    return gateway.client(definition["owner"], definition["name"], definition["max_tokens"])


# --- check: both gateways' data, against the platform's policy.


def config_problems(
    teams: Sequence[Team],
    routes: Sequence[Route],
    deployments: Sequence[Deployment],
    where: str,
    on: date | None = None,
) -> list[str]:
    """What's wrong with one gateway's data, as of a day (chapter 20's retirement dates)."""
    policy, models = load(POLICY), load(MODELS)
    problems = []
    for team in teams:
        if team.monthly_usd <= 0 or team.requests_per_minute < 1 or team.input_tokens_per_minute < 1:
            problems.append(f"{where}: team {team.name}: a budget and both limits must be more than 0.")
    deployed = {d.model for d in deployments}
    for route in routes:
        if not route.models:
            problems.append(f"{where}: route {route.name} has no models.")
        for model in route.models:
            at = f"{where}: route {route.name}: {model}"
            if model not in policy["models"]:
                problems.append(f"{at} isn't approved in agents/policy.toml, so it can't answer for anyone.")
                continue
            retiring = lifecycle(model, policy, models, on or today())
            if retiring is not None:
                problems.append(f"{at}: {retiring.reason}")
            if model not in deployed:
                problems.append(f"{at} has no deployment, so the gateway has nowhere to send it.")
    return problems


@dataclass
class Demo:
    teams: list[Team]
    routes: list[Route]
    deployments: list[Deployment]


def load_demo(path: Path = DEMO) -> Demo:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    routes = [
        Route(name, tuple(r["models"]), int(r.get("cache_seconds", 0))) for name, r in data["routes"].items()
    ]
    deployments = [Deployment(d["name"], d["model"]) for d in data["deployments"]]
    return Demo(teams_of(data), routes, deployments)


def describe(teams: Sequence[Team], routes: Sequence[Route], deployments: Sequence[Deployment]) -> list[str]:
    lines = [
        f"  team {t.name}: {money(t.monthly_usd)} a month, {t.requests_per_minute:,} requests and "
        f"{t.input_tokens_per_minute:,} input tokens a minute"
        for t in teams
    ]
    for r in routes:
        cached = f", cached for {r.cache_seconds}s" if r.cache_seconds else ""
        lines.append(f"  route {r.name}: {', '.join(r.models)}{cached}")
    places: dict[str, list[str]] = {}
    for d in deployments:
        places.setdefault(d.model, []).append(d.name)
    lines += [f"  {model} at {', '.join(names)}" for model, names in places.items()]
    return lines


def check(on: date | None = None) -> int:
    """Both gateways' data. That each agent's owner is a team is the policy's rule (agent_policy)."""
    policy = load(POLICY)
    lab_routes = [Route(d["name"], (d["model"],)) for d in definitions()]
    lab_deployments = [Deployment("anthropic", m) for m in policy["models"]]
    demo = load_demo()
    problems = config_problems(teams_of(policy), lab_routes, lab_deployments, "the lab", on)
    problems += config_problems(demo.teams, demo.routes, demo.deployments, "gateway/demo.toml", on)
    if on is not None:
        print(f"As of {on.isoformat()}.")
    print("The lab's gateway (agents/policy.toml and the agent definitions):")
    print("\n".join(describe(teams_of(policy), lab_routes, lab_deployments)))
    print("The demo's gateway (gateway/demo.toml):")
    print("\n".join(describe(demo.teams, demo.routes, demo.deployments)))
    if problems:
        print(f"\n{len(problems)} problem{'' if len(problems) == 1 else 's'}:")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    print(
        "\nEvery team has a budget and limits, and every model on a route is approved, tracked, not "
        "retiring within the policy's notice, and deployed somewhere."
    )
    return 0


# --- demo: a made-up organization, the real gateway.


class HandClock:
    """A clock the demo moves: sleeping moves it on, so a wait takes no real time."""

    def __init__(self, start: float) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class StandIn:
    """The demo's provider. Each deployment answers with a short summary, and reports the tokens it
    was sent; a deployment given failures raises or refuses them in order first."""

    failures: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def connect(self, deployment: Deployment, max_tokens: int) -> ModelClient:
        stand_in = self

        class Deployed:
            def complete(
                self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
            ) -> ModelResponse:
                queue = stand_in.failures.get((deployment.model, deployment.name), [])
                sent = round(request_chars(system, messages, tools) / CHARS_PER_TOKEN)
                if queue:
                    failure = queue.pop(0)
                    if failure == "refusal":
                        return ModelResponse("refusal", usage=Usage(0, 0))
                    raise Unavailable(failure)
                return ModelResponse("end_turn", "A short summary.", usage=Usage(sent, 120))

        return Deployed()


START = datetime(2026, 9, 1, 9, 0, tzinfo=UTC).timestamp()
SYSTEM = "You summarize helpdesk tickets for the team that owns them."
MAX_TOKENS = 1000
# What the demo asks, in order: (team, route, request, what fails first, seconds to wait before it).
STEPS: list[tuple[str, str, str, dict[tuple[str, str], list[str]], float]] = [
    ("support-tools", "summarize", "Summarize ticket 4.", {}, 0),
    ("support-tools", "summarize", "Summarize ticket 4.", {}, 2),
    (
        "support-tools",
        "summarize",
        "Summarize ticket 9.",
        {("claude-sonnet-5", "primary"): ["overloaded"]},
        2,
    ),
    ("support-tools", "triage", "Triage ticket 12.", {("claude-opus-5-5", "primary"): ["overloaded"]}, 2),
    ("support-tools", "summarize", "Summarize ticket 15.", {}, 2),
    (
        "support-tools",
        "summarize",
        "Summarize ticket 20.",
        {("claude-sonnet-5", "primary"): ["refusal"]},
        120,
    ),
    ("support-tools", "triage", "Triage ticket 21.", {("claude-opus-5-5", "primary"): ["refusal"]}, 2),
    ("billing", "summarize", "Summarize invoice 31.", {}, 2),
    ("billing", "summarize", "Summarize invoice 32.", {}, 1),
    ("billing", "summarize", "Summarize invoice 33.", {}, 1),
    ("billing", "summarize", "Summarize invoice 34.", {}, 1),
    ("billing", "summarize", "Summarize invoice 35.", {}, 40),
    ("billing", "summarize", "Summarize invoice 36.", {}, 60),
]


def demo(record: Path) -> int:
    found = load_demo()
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("", encoding="utf-8")  # the demo's record starts empty every run
    clock, stand_in = HandClock(START), StandIn()
    gateway = Gateway(
        found.teams,
        found.routes,
        found.deployments,
        stand_in.connect,
        CallLog(record, "gateway demo"),
        chars_per_token=CHARS_PER_TOKEN,
        clock=clock,
    )
    print("A made-up organization through the lab's gateway: two teams, two routes, a stand-in")
    print("provider and a clock the demo moves. Every line below is a line of the gateway's record.\n")
    for team, route, text, failures, wait in STEPS:
        clock.sleep(wait)
        for key, queue in failures.items():
            stand_in.failures.setdefault(key, []).extend(queue)
        before = len(read(record))
        asked = datetime.fromtimestamp(clock.time(), UTC).strftime("%H:%M:%S")
        try:
            response = gateway.client(team, route, MAX_TOKENS).complete(
                system=SYSTEM, messages=[Message("user", text)]
            )
            ended = "the answer" if response.stop_reason == "end_turn" else f"a {response.stop_reason}"
            ended = f"Got {ended}."
        except Refused as refused:
            ended = f"Refused: {refused}"
        except NothingAnswered as down:
            ended = str(down)
        print(f"{asked} {team}, {route}: {text} {ended}")
        for call in read(record)[before:]:
            where = f"{call.model} at {call.deployment}" if call.deployment else call.model
            why = f" ({call.error})" if call.error and call.outcome == "unavailable" else ""
            print(f"  {call.at[11:19]} {where}: {call.outcome}{why}, ${call.usd:.4f}")
    print()
    print("\n".join(report(read(record))))
    return 0


# --- report: cost and outcomes by team and route.


# The report's columns, and the outcomes each counts.
COLUMNS = (
    ("answered", ("ok",)),
    ("cached", ("cached",)),
    ("refusals", ("refusal",)),
    ("turned away", ("rate limited", "over the budget")),
    ("failed", ("unavailable", "error", "cut off", "over the cap")),
)


def report(calls: Sequence[Call]) -> list[str]:
    """A gateway record by team and route: what each spent, and how each attempt ended."""
    calls = [c for c in calls if c.team]
    if not calls:
        return ["No gateway calls recorded."]
    groups: dict[tuple[str, str], list[Call]] = {}
    for c in calls:
        groups.setdefault((c.team, c.route), []).append(c)
    rows = [("team", "route", *(name for name, _ in COLUMNS), "input tokens", "output tokens", "cost")]
    for (team, route), group in sorted(groups.items()):
        counts = [f"{sum(c.outcome in outcomes for c in group):,}" for _, outcomes in COLUMNS]
        tokens_in, tokens_out = (
            round(sum(c.input_tokens for c in group)),
            round(sum(c.output_tokens for c in group)),
        )
        rows.append(
            (team, route, *counts, f"{tokens_in:,}", f"{tokens_out:,}", f"${sum(c.usd for c in group):.4f}")
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(
            cell.ljust(w) if i < 2 else cell.rjust(w)
            for i, (cell, w) in enumerate(zip(row, widths, strict=True))
        )
        for row in rows
    ]
    months = sorted({c.at[:7] for c in calls})
    lines += [
        "",
        f"{len(calls):,} attempts in {', '.join(months)}, one line each. Turned away: the gateway "
        "refused the call for the team's rate or month. Failed: the provider couldn't answer, an "
        "error, or a cut-off answer.",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.gateway", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    checked = commands.add_parser(
        "check", help="check the lab's and the demo's gateway data against the policy"
    )
    checked.add_argument("--today", type=date.fromisoformat, help="check as if it were this day, YYYY-MM-DD")
    run = commands.add_parser("demo", help="a made-up organization through the gateway, with no model")
    run.add_argument("--record", type=Path, default=LAB / "records" / "gateway-demo.jsonl")
    summed = commands.add_parser("report", help="cost and outcomes by team and route")
    summed.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "check":
        return check(args.today)
    if args.command == "demo":
        return demo(args.record)
    try:
        print("\n".join(report(read(args.file))))
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
