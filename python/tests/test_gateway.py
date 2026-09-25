"""The model gateway (chapter 27): one front door that holds the provider's client, limits each
team's rate and month, routes to the cheapest model measured for the job, falls back when a
deployment is down or a model refuses, caches identical requests, and records every attempt with
the team that pays for it.

Everything here runs stand-in providers and a clock moved by hand; nothing calls a model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from helpdesk import evals
from helpdesk import gateway as command
from helpdesk.model.anthropic_client import AnthropicModel
from helpdesk.model.budget import price
from helpdesk.model.calls import CallLog, read, summary
from helpdesk.model.gateway import (
    Deployment,
    Gateway,
    NothingAnswered,
    OverBudget,
    RateLimited,
    Route,
    Team,
)
from helpdesk.model.types import Message, ModelResponse, ToolResult, Unavailable, Usage

OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5"
SEPT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC).timestamp()
TEAM = Team("support-tools", 40.0, 60, 200_000)


class Clock:
    def __init__(self, start: float = SEPT) -> None:
        self.now, self.slept = start, 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += seconds


class Provider:
    """Stand-in deployments. Each answers "ok" unless given failures to play first, and remembers
    every call it received."""

    def __init__(self, **plays: list[str]) -> None:
        self.plays = {key: list(queue) for key, queue in plays.items()}
        self.received: list[tuple[str, str]] = []

    def connect(self, deployment: Deployment, max_tokens: int) -> Any:
        provider = self

        class Deployed:
            def complete(self, **_: Any) -> ModelResponse:
                where = f"{deployment.model}@{deployment.name}"
                provider.received.append((deployment.model, deployment.name))
                queue = provider.plays.get(where, [])
                play = queue.pop(0) if queue else "ok"
                if play == "refusal":
                    return ModelResponse("refusal", usage=Usage(100, 0))
                if play == "boom":
                    raise KeyError("a bug, not an outage")
                if play == "cut":
                    return ModelResponse("max_tokens", "Half an", usage=Usage(1000, 1000))
                if play.startswith("wait "):
                    raise Unavailable("rate limited", float(play.split()[1]))
                if play != "ok":
                    raise Unavailable(play)
                return ModelResponse(
                    "end_turn", "Done.", usage=Usage(1000, 100), request_id=f"req_{len(provider.received)}"
                )

        return Deployed()


def build(
    tmp_path: Path,
    provider: Provider,
    routes: tuple[Route, ...] = (Route("summarize", (OPUS, SONNET)),),
    teams: tuple[Team, ...] = (TEAM,),
    clock: Clock | None = None,
    deployments: tuple[Deployment, ...] = (
        Deployment("primary", OPUS),
        Deployment("second-region", OPUS),
        Deployment("primary", SONNET),
    ),
) -> tuple[Gateway, Path, Clock]:
    clock = clock or Clock()
    path = tmp_path / "gateway.jsonl"
    found = Gateway(
        teams, routes, deployments, provider.connect, CallLog(path, "test"), chars_per_token=2.5, clock=clock
    )
    return found, path, clock


def ask(
    gateway: Gateway, text: str = "Summarize ticket 4.", team: str = "support-tools", route: str = "summarize"
) -> ModelResponse:
    return gateway.client(team, route, 1000).complete(
        system="You summarize.", messages=[Message("user", text)]
    )


def outcomes(path: Path) -> list[tuple[str, str, str]]:
    return [(c.model, c.deployment, c.outcome) for c in read(path)]


# --- Routing by cost, among the models measured for the job.


def test_the_cheapest_model_on_the_route_answers_and_the_line_names_who_pays(tmp_path):
    provider = Provider()
    gateway, path, _ = build(tmp_path, provider)
    ask(gateway)
    [line] = read(path)
    assert (line.model, line.deployment, line.outcome) == (SONNET, "primary", "ok")
    assert (line.team, line.route, line.request_id) == ("support-tools", "summarize", "req_1")
    assert line.usd == pytest.approx(price(SONNET, 1000, 100))


def test_a_model_that_isnt_on_the_route_is_never_tried_however_cheap(tmp_path):
    provider = Provider(**{f"{OPUS}@primary": ["overloaded"], f"{OPUS}@second-region": ["overloaded"]})
    deployments = (
        Deployment("primary", OPUS),
        Deployment("second-region", OPUS),
        Deployment("primary", SONNET),
    )
    gateway, _, _ = build(tmp_path, provider, routes=(Route("triage", (OPUS,)),), deployments=deployments)
    with pytest.raises(
        NothingAnswered, match="claude-opus-5-5 at primary, overloaded; claude-opus-5-5 at second-region"
    ):
        ask(gateway, route="triage")
    assert SONNET not in {model for model, _ in provider.received}


# --- Falling back.


def test_a_deployment_that_is_down_rests_and_the_same_model_answers_elsewhere(tmp_path):
    provider = Provider(**{f"{OPUS}@primary": ["overloaded"]})
    gateway, path, clock = build(tmp_path, provider, routes=(Route("triage", (OPUS,)),))
    ask(gateway, route="triage")
    assert outcomes(path) == [(OPUS, "primary", "unavailable"), (OPUS, "second-region", "ok")]
    assert read(path)[0].error == "overloaded"
    clock.sleep(10)
    ask(gateway, "Another ticket.", route="triage")  # primary is still cooling down: not tried
    assert provider.received[-1] == (OPUS, "second-region")
    clock.sleep(60)
    ask(gateway, "A third ticket.", route="triage")
    assert provider.received[-1] == (OPUS, "primary")


def test_a_deployment_rests_for_as_long_as_the_provider_asked(tmp_path):
    provider = Provider(**{f"{OPUS}@primary": ["wait 5"]})
    gateway, _, clock = build(tmp_path, provider, routes=(Route("triage", (OPUS,)),))
    ask(gateway, route="triage")
    clock.sleep(6)  # the provider asked for 5 seconds, not the gateway's own 60
    ask(gateway, "Another ticket.", route="triage")
    assert provider.received[-1] == (OPUS, "primary")


def test_when_the_cheaper_model_is_down_the_next_model_on_the_route_answers(tmp_path):
    provider = Provider(**{f"{SONNET}@primary": ["rate limited"]})
    gateway, path, _ = build(tmp_path, provider)
    ask(gateway)
    assert outcomes(path) == [(SONNET, "primary", "unavailable"), (OPUS, "primary", "ok")]


def test_a_refusal_goes_to_the_next_model_on_the_route(tmp_path):
    provider = Provider(**{f"{SONNET}@primary": ["refusal"]})
    gateway, path, _ = build(tmp_path, provider)
    assert ask(gateway).stop_reason == "end_turn"
    assert outcomes(path) == [(SONNET, "primary", "refusal"), (OPUS, "primary", "ok")]


def test_with_no_other_model_on_the_route_the_refusal_is_the_answer(tmp_path):
    provider = Provider(**{f"{OPUS}@primary": ["refusal"]})
    gateway, path, _ = build(tmp_path, provider, routes=(Route("triage", (OPUS,)),))
    assert ask(gateway, route="triage").stop_reason == "refusal"
    # The second region runs the same model, which would refuse again: it isn't asked.
    assert provider.received == [(OPUS, "primary")]
    assert outcomes(path) == [(OPUS, "primary", "refusal")]


def test_an_error_that_isnt_an_outage_is_recorded_and_raised_without_a_fallback(tmp_path):
    provider = Provider(**{f"{SONNET}@primary": ["boom"]})
    gateway, path, _ = build(tmp_path, provider)
    with pytest.raises(KeyError):
        ask(gateway)
    assert [(c.outcome, c.error) for c in read(path)] == [("error", "KeyError")]
    assert provider.received == [(SONNET, "primary")]


# --- Rate limits: each team's share of the organization's minute.


def test_a_short_wait_for_room_in_the_minute_is_waited_and_a_long_one_is_refused(tmp_path):
    team = Team("billing", 10.0, 3, 20_000)
    provider = Provider()
    gateway, path, clock = build(tmp_path, provider, teams=(team,))
    for n in range(3):
        ask(gateway, f"Invoice {n}.", team="billing")
        clock.sleep(1)
    with pytest.raises(RateLimited, match="there's room in 57s") as refused:
        ask(gateway, "Invoice 3.", team="billing")
    assert refused.value.retry_after == pytest.approx(57)
    assert len(provider.received) == 3  # the refused call was never made
    assert read(path)[-1].outcome == "rate limited"
    clock.sleep(40)  # 43 seconds after the first: room in 17, which the gateway waits for
    ask(gateway, "Invoice 4.", team="billing")
    assert clock.slept == pytest.approx(3 + 40 + 17)
    assert len(provider.received) == 4


def test_a_request_bigger_than_the_teams_whole_minute_is_refused_at_once(tmp_path):
    team = Team("billing", 10.0, 3, 100)
    gateway, _, clock = build(tmp_path, Provider(), teams=(team,))
    with pytest.raises(RateLimited, match="can never be sent"):
        ask(gateway, "x" * 1000, team="billing")
    assert clock.slept == 0


def test_the_minute_counts_the_providers_tokens_not_the_estimate(tmp_path):
    # The estimate of this request is under 100 tokens; the provider says 1,000 were used.
    team = Team("billing", 10.0, 10, 1_000)
    gateway, _, _ = build(tmp_path, Provider(), teams=(team,))
    ask(gateway, team="billing")
    with pytest.raises(RateLimited):
        ask(gateway, "Another.", team="billing")


# --- The month: a team's budget, checked before the call at its worst.


def test_a_call_that_could_take_the_team_past_its_month_is_refused_before_it_is_made(tmp_path):
    # The first call costs what sonnet used; the second could cost at least opus's max_tokens, since
    # opus is the dearest model on the route. The month has room for the first and not both.
    team = Team("billing", price(SONNET, 1000, 100) + price(OPUS, 0, 1000) - 0.0001, 60, 200_000)
    provider = Provider()
    gateway, path, _ = build(tmp_path, provider, teams=(team,))
    ask(gateway, team="billing")
    with pytest.raises(OverBudget, match="Nothing was sent"):
        ask(gateway, "Another.", team="billing")
    assert len(provider.received) == 1
    assert read(path)[-1].outcome == "over the budget"


def test_the_months_spend_is_read_back_from_the_record_and_a_new_month_starts_at_zero(tmp_path):
    team = Team("billing", 0.03, 60, 200_000)
    gateway, path, clock = build(tmp_path, Provider(), teams=(team,))
    ask(gateway, team="billing")
    spent = gateway.month_spent("billing")
    assert spent > 0
    restarted, _, _ = build(tmp_path, Provider(), teams=(team,), clock=clock)
    assert restarted.month_spent("billing") == pytest.approx(spent)
    clock.now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC).timestamp()
    assert restarted.month_spent("billing") == 0


def test_an_unknown_team_or_route_is_named_with_the_ones_the_gateway_knows(tmp_path):
    gateway, _, _ = build(tmp_path, Provider())
    with pytest.raises(
        ValueError, match="'sales' isn't a team the gateway knows. The teams are support-tools"
    ):
        gateway.client("sales", "summarize", 1000)
    with pytest.raises(ValueError, match="The routes are summarize"):
        gateway.client("support-tools", "translate", 1000)


# --- The cache: identical requests, one team, for a while.


def test_an_identical_request_is_answered_from_the_cache_with_no_call_and_no_cost(tmp_path):
    team = Team("billing", 10.0, 1, 200_000)
    provider = Provider()
    gateway, path, clock = build(
        tmp_path, provider, routes=(Route("summarize", (OPUS, SONNET), 300),), teams=(team,)
    )
    first = ask(gateway, team="billing")
    assert ask(gateway, team="billing") is first  # one request a minute, and the cache took no room
    assert len(provider.received) == 1
    cached = read(path)[-1]
    assert (cached.outcome, cached.usd, cached.model) == ("cached", 0.0, SONNET)
    clock.sleep(301)
    ask(gateway, team="billing")
    assert len(provider.received) == 2


def test_the_cache_is_per_team_and_any_difference_in_the_request_misses_it(tmp_path):
    teams = (TEAM, Team("billing", 10.0, 60, 200_000))
    provider = Provider()
    gateway, _, _ = build(tmp_path, provider, routes=(Route("summarize", (OPUS, SONNET), 300),), teams=teams)
    ask(gateway)
    ask(gateway, team="billing")  # the same words from another team
    assert len(provider.received) == 2
    client = gateway.client("support-tools", "summarize", 1000)
    turn = [
        Message("user", "Summarize ticket 4."),
        Message("user", tool_results=(ToolResult("1", "status: open"),)),
    ]
    client.complete(system="You summarize.", messages=turn)
    changed = [turn[0], Message("user", tool_results=(ToolResult("1", "status: closed"),))]
    client.complete(system="You summarize.", messages=changed)
    assert len(provider.received) == 4


def test_only_a_finished_answer_is_cached(tmp_path):
    provider = Provider(**{f"{SONNET}@primary": ["cut"]})
    gateway, path, _ = build(tmp_path, provider, routes=(Route("summarize", (OPUS, SONNET), 300),))
    assert ask(gateway).stop_reason == "max_tokens"
    ask(gateway)
    assert len(provider.received) == 2
    assert [c.outcome for c in read(path)] == ["cut off", "ok"]


def test_a_cached_answer_is_not_a_failure_in_the_summary(tmp_path):
    gateway, path, _ = build(tmp_path, Provider(), routes=(Route("summarize", (OPUS, SONNET), 300),))
    ask(gateway)
    ask(gateway)
    assert "Failed: none" in summary(read(path), 2.5)[-1]


def test_a_route_without_a_cache_time_never_caches(tmp_path):
    provider = Provider()
    gateway, _, _ = build(tmp_path, provider)
    ask(gateway)
    ask(gateway)
    assert len(provider.received) == 2


# --- The adapter: what counts as an outage, and the provider's request id.


class StatusError(Exception):
    def __init__(self, status: int, retry: str | None = None) -> None:
        super().__init__(status)
        self.status_code = status
        self.response = SimpleNamespace(headers={"retry-after": retry} if retry else {})


class APIConnectionError(Exception):
    pass


class APITimeoutError(APIConnectionError):
    pass


@pytest.mark.parametrize(
    ("error", "kind", "wait"),
    [
        (StatusError(429, "12"), "rate limited", 12.0),
        (StatusError(429), "rate limited", None),
        (StatusError(529), "overloaded", None),
        (StatusError(500), "server error", None),
        (APITimeoutError("slow"), "no connection", None),
    ],
)
def test_an_outage_from_the_provider_becomes_unavailable_with_its_wait(error, kind, wait):
    def create(**_: Any) -> Any:
        raise error

    model = AnthropicModel(SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(Unavailable) as down:
        model.complete(system="s", messages=[Message("user", "hi")])
    assert (down.value.kind, down.value.retry_after) == (kind, wait)


def test_a_request_the_provider_rejects_is_raised_as_it_is(tmp_path):
    def create(**_: Any) -> Any:
        raise StatusError(400)

    model = AnthropicModel(SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(StatusError):
        model.complete(system="s", messages=[Message("user", "hi")])


def test_the_adapter_passes_on_the_providers_request_id():
    response = SimpleNamespace(stop_reason="end_turn", content=[], usage=None, _request_id="req_011")
    model = AnthropicModel(SimpleNamespace(messages=SimpleNamespace(create=lambda **_: response)))
    assert model.complete(system="s", messages=[Message("user", "hi")]).request_id == "req_011"


# --- The lab's gateway: every real call goes through it.


def test_each_agents_route_is_the_model_its_definition_names():
    lab = command.lab_gateway(connect=Provider().connect)
    assert {name: route.models for name, route in lab.routes.items()} == {
        d["name"]: (d["model"],) for d in command.definitions()
    }
    assert set(lab.teams) == {"support-tools"}


def test_a_real_run_goes_through_the_gateway_and_is_recorded_for_the_owners_team(gateway_record):
    made: list[dict[str, Any]] = []

    def create(**request: Any) -> Any:
        made.append(request)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="Hi.")],
            usage=SimpleNamespace(input_tokens=12, output_tokens=3),
            _request_id="req_abc",
        )

    definition = evals.triage_definition()
    model = evals.real_model(definition, SimpleNamespace(messages=SimpleNamespace(create=create)))
    model.complete(system="s", messages=[Message("user", "hi")])
    [line] = read(gateway_record)
    assert (line.team, line.route, line.model, line.deployment) == (
        "support-tools",
        "triage",
        definition["model"],
        "anthropic",
    )
    assert (line.input_tokens, line.tokens_from, line.request_id) == (12, "provider", "req_abc")
    assert made[0]["model"] == definition["model"]


def test_a_definition_whose_model_isnt_on_its_route_is_refused():
    definition = {**evals.triage_definition(), "model": SONNET}
    with pytest.raises(ValueError, match="isn't on its route"):
        command.for_agent(definition, SimpleNamespace(messages=None))


# --- The command: check, demo and report.


def test_the_check_passes_on_the_lab_and_the_demo(capsys):
    assert command.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "route triage: claude-opus-5-5" in out
    assert "route summarize: claude-opus-5-5, claude-sonnet-5, cached for 300s" in out


def test_the_check_names_a_route_to_an_unapproved_retiring_or_undeployed_model():
    routes = [Route("summarize", ("claude-fable-5-1", "claude-haiku-4-5-20251001", SONNET))]
    problems = command.config_problems(
        [TEAM], routes, [Deployment("primary", "claude-haiku-4-5-20251001")], "demo"
    )
    assert any("claude-fable-5-1 isn't approved" in p for p in problems)
    assert any("claude-haiku-4-5-20251001 isn't approved" in p for p in problems)
    assert any("claude-sonnet-5 has no deployment" in p for p in problems)


def test_the_check_names_an_approved_model_near_retirement(monkeypatch):
    monkeypatch.setenv("AGENT_POLICY_TODAY", "2027-06-01")
    problems = command.config_problems(
        [TEAM], [Route("summarize", (SONNET,))], [Deployment("p", SONNET)], "demo"
    )
    assert problems and "claude-sonnet-5 may retire as soon as 2027-06-30" in problems[0]


def test_the_check_as_of_a_later_day_names_every_route_to_a_model_near_retirement(capsys):
    # claude-sonnet-5 may retire from 2027-06-30; the policy moves agents 90 days before.
    assert command.main(["check", "--today", "2027-04-15"]) == 1
    out = capsys.readouterr().out
    assert "As of 2027-04-15." in out
    assert "the lab: route judge-second: claude-sonnet-5: claude-sonnet-5 may retire" in out
    assert "gateway/demo.toml: route summarize: claude-sonnet-5: claude-sonnet-5 may retire" in out


def test_the_check_names_a_team_without_a_budget():
    problems = command.config_problems([Team("billing", 0.0, 3, 100)], [], [], "demo")
    assert problems == ["demo: team billing: a budget and both limits must be more than 0."]


def test_the_demo_shows_each_thing_the_gateway_does(tmp_path, capsys):
    record = tmp_path / "demo.jsonl"
    assert command.main(["demo", "--record", str(record)]) == 0
    out = capsys.readouterr().out
    for seen in (
        "claude-sonnet-5 at primary: ok",
        "claude-sonnet-5: cached",
        "claude-sonnet-5 at primary: unavailable (overloaded)",
        "claude-opus-5-5 at second-region: ok",
        "Got a refusal",
        "rate limited",
        "over the budget",
    ):
        assert seen in out
    lines = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
    assert all(line["team"] and line["route"] for line in lines)
    # A second run starts from an empty record, so it prints the same.
    assert command.main(["demo", "--record", str(record)]) == 0
    assert capsys.readouterr().out == out


def test_the_report_adds_up_by_team_and_route(tmp_path, capsys):
    record = tmp_path / "demo.jsonl"
    command.main(["demo", "--record", str(record)])
    capsys.readouterr()
    assert command.main(["report", str(record)]) == 0
    out = capsys.readouterr().out
    rows = {tuple(line.split()[:2]): line.split()[2:] for line in out.splitlines()[1:4]}
    assert rows[("support-tools", "triage")][:5] == ["1", "0", "1", "0", "1"]
    total = sum(c.usd for c in read(record))
    shown = sum(float(cells[-1].lstrip("$")) for cells in rows.values())
    assert shown == pytest.approx(total, abs=0.0003)
