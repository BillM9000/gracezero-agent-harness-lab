"""Composition root for evaluations as a gate (chapter 23).

python -m helpdesk.gate check             on every change, with no model: the gate's rules can fail
                                          a case and rarely fail one by chance, and evals/promoted.json,
                                          the record of the last promotion, matches what the model is
                                          given now
python -m helpdesk.gate estimate          what one run of the gate sends, and what it would cost
python -m helpdesk.gate run               the golden sets and the judge's calibration, compared with
                                          the record; exits 1 on a regression
python -m helpdesk.gate run --promote     the same, and if it passes, writes the record

A change to a prompt, a model, a tool, a rubric or a golden set changes what the record holds, so
check fails until the gate has run with the change and passed: a promotion. --real runs the gate on
Anthropic's API and is billed, so it needs --max-usd: it refuses to start when the estimate doesn't
fit under the cap, and stops before any call that could take it past. Without --real, the mock plays
each case's reference, which shows the gate works and says nothing about a model; the record says
which one measured it, and evals/gate.json's require_real decides whether the mock may promote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_policy import today
from helpdesk import evals, judge
from helpdesk.assistant.gating import (
    Counts,
    Rule,
    Verdict,
    chance_of_at_least,
    healthy_suite_fails,
    held_false_passes,
    judge_calibration,
    judge_suite,
)
from helpdesk.assistant.grading import pass_hat_k
from helpdesk.kb import CHARS_PER_TOKEN
from helpdesk.model.anthropic_client import tool_to_api
from helpdesk.model.budget import Budget, BudgetReached, Spend, price
from helpdesk.model.cost import PRICES, PRICES_READ
from helpdesk.model.types import ModelClient
from helpdesk.services import access

RULES = evals.EVALS / "gate.json"
RECORD = evals.EVALS / "promoted.json"
SUITES = ("tasks", "reasons", "injections")
PARTS = (*SUITES, "judge")
K = 3  # the k of the pass^k reported beside each suite (chapter 21)


# --- The rules, and what the model is given.


@dataclass(frozen=True)
class Settings:
    rule: Rule
    judge_trials: int
    require_real: bool


def settings(path: Path | None = None) -> Settings:
    data = json_file(path or RULES)
    regression = data["regression"]
    unknown = sorted(set(data["every_trial"]) - set(SUITES))
    if unknown:
        raise ValueError(f"every_trial names {', '.join(unknown)}; the suites are {', '.join(SUITES)}")
    rule = Rule(
        trials=data["trials"],
        expected=regression["expected_pass_rate"],
        false_alarm=regression["false_alarm"],
        every_trial=frozenset(data["every_trial"]),
        suite_min_cases=regression["suite_min_cases"],
    )
    if data["judge_trials"] < 1:
        raise ValueError("judge_trials must be 1 or more")
    return Settings(rule, data["judge_trials"], data["require_real"])


def digest(value: Any) -> str:
    """A fingerprint of what the model is given, not of the file's bytes: parsed first, so a
    comment or a blank line changes nothing."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def configuration() -> dict[str, str]:
    """Everything a promotion measured: what the assistant and the judge are told and which models
    they use, the tools as the model sees them, and the golden sets, rubric and labels it was
    measured with. A change to any of them is a change to what ships, or to what measures it."""
    triage = evals.triage_definition()
    with evals.helpdesk() as (conn, _):
        person = access.find_person(conn, "sam")
        tools = [tool_to_api(spec) for spec in evals.toolbox(conn, person, triage, "triage").specs]
    parts: dict[str, Any] = {
        "agents/triage.toml: the assistant's model, limits, tools and system prompt": triage,
        "the assistant's tools, as the model sees them": tools,
        "agents/judge.toml: the judge's model, limits and system prompt": judge.definition("same"),
        "evals/rubrics/reply.json: the judge's criteria": json_file(judge.RUBRICS / "reply.json"),
        "evals/judged.json: the labeled replies": json_file(judge.LABELED),
    }
    for suite in SUITES:
        parts[f"evals/{evals.SUITES[suite].name}: a golden set"] = json_file(evals.SUITES[suite])
    return {name: digest(value) for name, value in parts.items()}


# --- Measuring: the golden sets and the judge.


@dataclass
class Measured:
    trials: int
    suites: dict[str, dict[str, Counts]]
    judge: dict[str, Any] | None
    spend: dict[str, Spend]  # what each part sent


def spent_since(budget: Budget, before: Spend) -> Spend:
    now = budget.spent
    return Spend(
        now.calls - before.calls,
        now.input_tokens - before.input_tokens,
        now.output_tokens - before.output_tokens,
        now.usd - before.usd,
    )


def snapshot(budget: Budget) -> Spend:
    s = budget.spent
    return Spend(s.calls, s.input_tokens, s.output_tokens, s.usd)


def chooser(real: bool, vary: int | None, budget: Budget) -> Callable[[evals.Prepared], ModelClient]:
    definition = evals.triage_definition()
    if real:
        return evals.real_choice(definition, budget)
    mock = evals.mock_choice(evals.reference_only if vary is None else evals.stand_in(vary))
    return lambda prepared: budget.wrap(mock(prepared), definition["model"], definition["max_tokens"])


def measure(
    parts: Sequence[str], trials: int, judge_trials: int, real: bool, vary: int | None, budget: Budget
) -> Measured:
    choose = chooser(real, vary, budget)
    definition = evals.triage_definition()
    result = Measured(trials, {}, None, {})
    for suite in (s for s in SUITES if s in parts):
        before = snapshot(budget)
        tallies = evals.run_trials(evals.LOADERS[suite](), "triage", trials, definition, choose)
        result.suites[suite] = {
            f"{t.case.id} ({t.case.person})": (t.passed, len(t.outcomes)) for t in tallies
        }
        result.spend[suite] = spent_since(budget, before)
    if "judge" in parts:
        before = snapshot(budget)
        calibration = judge.calibrate("same", judge_trials, real, budget=budget)
        agreement = calibration.agreement()
        false_passes = {
            f"{reply.id} {c.id}": sum(t[reply.id].of(c.id).outcome == "pass" for t in calibration.trials)
            for reply in calibration.replies
            for c in calibration.rubric.criteria
            if reply.person[c.id] == "fail"
        }
        result.judge = {
            "trials": judge_trials,
            "agree": agreement.agree,
            "judged": agreement.judged,
            "rubber_stamp": agreement.person_passed,
            "false_passes": false_passes,
        }
        result.spend["judge"] = spent_since(budget, before)
    return result


# --- The record.


def load_record(path: Path | None = None) -> dict[str, Any] | None:
    path = path or RECORD
    return json_file(path) if path.exists() else None


def record_of(measured: Measured, real: bool, cost: Spend) -> dict[str, Any]:
    triage, found = evals.triage_definition(), judge.definition("same")
    assert measured.judge is not None
    return {
        "about": (
            "The last promotion (chapter 23): what the model was given when the gate passed, and what the "
            "gate measured. Written by python -m helpdesk.gate run --promote, never by hand. python -m "
            "helpdesk.gate check fails when what the model is given no longer matches."
        ),
        "promoted": today().isoformat(),
        "measured_on": f"{triage['model']} and {found['model']} on Anthropic's API" if real else "the mock",
        "configuration": configuration(),
        "trials": measured.trials,
        # Trials passed, by case; every case ran "trials" times.
        "suites": {
            suite: {case: c[0] for case, c in cases.items()} for suite, cases in measured.suites.items()
        },
        "judge": {
            "trials": measured.judge["trials"],
            "agree": measured.judge["agree"],
            "judged": measured.judge["judged"],
            "false_passes": sorted(
                held_false_passes(measured.judge["false_passes"], measured.judge["trials"])
            ),
        },
        "sent": {
            "calls": cost.calls,
            "input_tokens": round(cost.input_tokens),
            "output_tokens": round(cost.output_tokens),
            "usd": round(cost.usd, 2),
            "prices_read": PRICES_READ,
        },
    }


# --- Comparing a run with the record.


def recorded(record: dict[str, Any] | None, suite: str) -> dict[str, Counts]:
    """A suite's counts at promotion: (passed, trials) by case."""
    if not record:
        return {}
    return {case: (passed, record["trials"]) for case, passed in record["suites"].get(suite, {}).items()}


def verdicts(measured: Measured, record: dict[str, Any] | None, rule: Rule) -> dict[str, Verdict]:
    found: dict[str, Verdict] = {}
    for suite, after in measured.suites.items():
        found[suite] = judge_suite(suite, recorded(record, suite), after, rule)
    if measured.judge is not None:
        j = measured.judge
        before = record["judge"]["false_passes"] if record and "judge" in record else None
        held = held_false_passes(j["false_passes"], j["trials"])
        found["judge"] = judge_calibration(before, held, j["agree"], j["rubber_stamp"], j["judged"])
    return found


def summary_rows(measured: Measured, record: dict[str, Any] | None, found: Mapping[str, Verdict], rule: Rule):
    rows = [("part", "cases", "passed now", "at promotion", f"pass^{K} now", "verdict")]
    for suite, after in measured.suites.items():
        was = recorded(record, suite)
        passed, runs = sum(p for p, _ in after.values()), sum(n for _, n in after.values())
        before = f"{sum(p for p, _ in was.values())} of {sum(n for _, n in was.values())}" if was else "none"
        k = min(K, measured.trials)
        hat = sum(pass_hat_k(n, p, k) for p, n in after.values()) / len(after)
        rows.append(
            (suite, str(len(after)), f"{passed} of {runs}", before, f"{hat:.0%}", verdict_word(found[suite]))
        )
    if measured.judge is not None:
        j = measured.judge
        was = (record or {}).get("judge")
        before = f"{was['agree']} of {was['judged']} agree" if was else "none"
        now = f"{j['agree']} of {j['judged']} agree"
        labels = j["judged"] // j["trials"]
        rows.append(("judge", f"{labels} labels", now, before, "", verdict_word(found["judge"])))
    return rows


def verdict_word(verdict: Verdict) -> str:
    return "pass" if verdict.passed else "FAIL"


def model_line(real: bool, vary: int | None) -> str:
    if real:
        return "Model: the definitions' models on Anthropic's API; every call is billed."
    if vary is None:
        return "Model: the mock, playing each case's reference solution, so every trial is the same."
    return (
        f"Model: the mock, standing in for a model that varies (seed {vary}): each trial plays the\n"
        "reference 70% of the time and a scripted mistake otherwise. The lab chose those odds."
    )


def cost_line(spend: Spend, real: bool) -> str:
    billed = "Billed, as the provider counted it." if real else "On the mock, nothing was billed."
    return (
        f"Sent (est.): {spend.calls:,} calls, {round(spend.input_tokens):,} input and "
        f"{round(spend.output_tokens):,} output tokens,\n"
        f"${spend.usd:.2f} at the prices read {PRICES_READ}. {billed}"
    )


# --- The commands.


def total(spend: Mapping[str, Spend]) -> Spend:
    out = Spend()
    for s in spend.values():
        out.calls += s.calls
        out.input_tokens += s.input_tokens
        out.output_tokens += s.output_tokens
        out.usd += s.usd
    return out


@dataclass(frozen=True)
class Estimate:
    spend: dict[str, Spend]
    worst_call: float
    most_calls: dict[str, int]
    most_output_usd: float


def estimate(parts: Sequence[str], trials: int, judge_trials: int) -> Estimate:
    """What a run sends, measured on the mock's shortest paths, the references: a floor, since a
    real model can take more turns and write more. The ceiling is what the definitions allow: every
    trial at its turn limit, every call writing max_tokens."""
    budget = Budget(None, CHARS_PER_TOKEN)
    measured = measure(parts, trials, judge_trials, real=False, vary=None, budget=budget)
    triage, found = evals.triage_definition(), judge.definition("same")
    most_calls: dict[str, int] = {}
    most_output = 0.0
    for suite, cases in measured.suites.items():
        most_calls[suite] = len(cases) * trials * triage["max_turns"]
        most_output += price(triage["model"], 0, most_calls[suite] * triage["max_tokens"])
    if measured.judge is not None:
        most_calls["judge"] = measured.judge["judged"] * found["max_turns"]  # judged counts every trial
        most_output += price(found["model"], 0, most_calls["judge"] * found["max_tokens"])
    return Estimate(measured.spend, budget.worst_call, most_calls, most_output)


def print_estimate(found: Estimate, trials: int, judge_trials: int) -> None:
    rows = [("part", "trials", "calls", "input tokens", "output tokens", "cost", "calls at most")]
    for part, s in found.spend.items():
        rows.append(
            (
                part,
                str(judge_trials if part == "judge" else trials),
                f"{s.calls:,}",
                f"{round(s.input_tokens):,}",
                f"{round(s.output_tokens):,}",
                f"${s.usd:.2f}",
                f"{found.most_calls[part]:,}",
            )
        )
    whole = total(found.spend)
    rows.append(
        (
            "all",
            "",
            f"{whole.calls:,}",
            f"{round(whole.input_tokens):,}",
            f"{round(whole.output_tokens):,}",
            f"${whole.usd:.2f}",
            f"{sum(found.most_calls.values()):,}",
        )
    )
    print("\n".join(evals.table(rows, (False, True, True, True, True, True, True))))
    models = sorted({evals.triage_definition()["model"], judge.definition("same")["model"]})
    prices = "; ".join(f"{m} ${PRICES[m][0]:g} in, ${PRICES[m][1]:g} out" for m in models)
    print(
        "\nMeasured on the mock's shortest paths, the references. Tokens are estimated at "
        f"{CHARS_PER_TOKEN}\ncharacters each and priced per million as read {PRICES_READ}: {prices}.\n"
        "A real model takes more turns and writes more. At its turn limits a run makes the calls in the\n"
        "last column, and their output alone, at max_tokens a call, could cost "
        f"${found.most_output_usd:,.2f}.\nA capped run also needs room for one call at its worst: "
        f"${found.worst_call:.2f}."
    )


def run_gate(
    parts: Sequence[str],
    real: bool,
    vary: int | None,
    max_usd: float | None,
    promote: bool,
    trials: int | None,
) -> int:
    config = settings()
    rule, n = config.rule, trials or config.rule.trials
    if n != rule.trials:
        rule = Rule(n, rule.expected, rule.false_alarm, rule.every_trial, rule.suite_min_cases)
    record = load_record()
    if promote and config.require_real and not real:
        print("evals/gate.json requires a real model to promote (require_real): add --real and --max-usd.")
        return 1
    if max_usd is not None:
        found = estimate(parts, n, config.judge_trials)
        need = total(found.spend).usd + found.worst_call
        print(
            f"Estimate: ${total(found.spend).usd:.2f} on the mock's shortest paths, plus room for one call "
            f"at its worst, ${found.worst_call:.2f}."
        )
        if need > max_usd:
            print(f"Refusing to start: that's ${need:.2f}, over the ${max_usd:.2f} cap. Nothing ran.")
            return 1
    budget = Budget(max_usd, CHARS_PER_TOKEN)
    promoted = f"promoted {record['promoted']}, on {record['measured_on']}" if record else "no promotion yet"
    print(f"Gate: evals/gate.json, {n} trials a case. Record: evals/promoted.json ({promoted}).")
    print(model_line(real, vary))
    if real:
        print(f"Capped at ${max_usd:.2f}.")
    print()
    try:
        measured = measure(parts, n, config.judge_trials, real, vary, budget)
    except BudgetReached as stop:
        print(f"The cap stopped the run: {stop}")
        print("A gate that didn't finish fails, and nothing is promoted.")
        return 1
    found = verdicts(measured, record, rule)
    print(
        "\n".join(
            evals.table(summary_rows(measured, record, found, rule), (False, True, True, True, True, False))
        )
    )
    failures = [f"  {part}: {f}" for part, v in found.items() for f in v.failures]
    notes = [f"  {part}: {f}" for part, v in found.items() for f in v.notes]
    if failures:
        print("\nFails the gate:\n" + "\n".join(failures))
    if notes:
        print("\nReported, not gating:\n" + "\n".join(notes))
    spend = total(measured.spend)
    print("\n" + cost_line(spend, real))
    if failures:
        print("The gate fails: this change doesn't ship until the failures above are explained or fixed.")
        return 1
    print("The gate passes.")
    if promote:
        RECORD.write_text(json.dumps(record_of(measured, real, spend), indent=2) + "\n", encoding="utf-8")
        print(f"Promoted: evals/{RECORD.name} now records this configuration and these results.")
    return 0


def check(rules: Path | None = None, record_path: Path | None = None) -> int:
    rules, record_path = rules or RULES, record_path or RECORD
    problems: list[str] = []
    try:
        config = settings(rules)
    except (ValueError, KeyError) as error:
        print(f"evals/{rules.name}: {error}")
        return 1
    rule = config.rule
    fails_at = rule.fails_at
    if fails_at is None:
        problems.append(
            f"evals/{rules.name}: with {rule.trials} trials, no number of failures is rare enough for a case "
            f"passing {rule.expected:.0%} of the time, so the gate could never fail one. Run more trials."
        )
    else:
        by_chance = chance_of_at_least(fails_at, rule.trials, 1 - rule.expected)
        caught = chance_of_at_least(fails_at, rule.trials, 0.5)
        every = ", ".join(sorted(rule.every_trial)) or "no suite"
        print(
            f"evals/{rules.name}: {rule.trials} trials a case. A case that passed every trial at promotion "
            f"fails the gate\nat {fails_at} failed trials. One still passing {rule.expected:.0%} of the time "
            f"does that by chance {by_chance:.1%} of the time;\none now passing half the time is caught "
            f"{caught:.0%} of the time. {every.capitalize()} allows no failed trial."
        )
    record = load_record(record_path)
    if record is not None and fails_at is not None:
        problems.extend(suite_rules(rule, record, rules.name))
    if record is None:
        problems.append(
            f"evals/{record_path.name} is missing: nothing has passed the gate. Run python -m "
            "helpdesk.gate run --promote (with --real --max-usd DOLLARS to measure a model)."
        )
    else:
        now = configuration()
        was = record["configuration"]
        changed = sorted(name for name in now.keys() | was.keys() if now.get(name) != was.get(name))
        if changed:
            problems.append(
                f"evals/{record_path.name}: changed since the promotion of {record['promoted']}:\n"
                + "\n".join(f"  {name}" for name in changed)
                + "\nA change to these ships only after the gate passes with it. Run python -m "
                "helpdesk.gate run --real\n--max-usd DOLLARS --promote (or, on the mock, python -m "
                f"helpdesk.gate run --promote),\nand commit evals/{record_path.name} with the change."
            )
        else:
            print(
                f"evals/{record_path.name}: promoted {record['promoted']}, measured on "
                f"{record['measured_on']}. What the model is\ngiven, and the sets that measured it, "
                f"are as recorded ({len(now)} fingerprints)."
            )
        on_mock = record["measured_on"] == "the mock"
        if on_mock and config.require_real:
            problems.append(
                f"evals/{rules.name} requires a real model's promotion (require_real), and the record was "
                "measured on the mock."
            )
        elif on_mock:
            print(
                "Measured on the mock, the record shows the gate works, not how any model does\n"
                f"(evals/{rules.name}: require_real is false)."
            )
    if problems:
        print("\n".join(problems))
        return 1
    return 0


def suite_rules(rule: Rule, record: dict[str, Any], rules_name: str) -> list[str]:
    """Print, for each gated suite in the record, where the suite rule fails it and how often a
    healthy suite fails the gate by chance; return a problem for a suite rule that could never fail."""
    problems: list[str] = []
    lines = [
        "A suite fails the gate when the cases that passed every trial at promotion, added up, fail at least:"
    ]
    for suite in SUITES:
        if suite in rule.every_trial or suite not in record["suites"]:
            continue
        cases = sum(passed == record["trials"] for passed in record["suites"][suite].values())
        healthy = healthy_suite_fails(cases, rule)
        if cases < rule.suite_min_cases:
            lines.append(
                f"  {suite}: no suite rule ({cases} cases, under suite_min_cases, {rule.suite_min_cases});\n"
                f"  a healthy {suite} suite fails the gate {healthy:.1%} of the time."
            )
            continue
        suite_at = rule.suite_fails_at(cases)
        if suite_at is None:
            problems.append(
                f"evals/{rules_name}: no total of failures over {suite}'s {cases} cases is rare enough, "
                "so the suite rule could never fail it. Run more trials."
            )
            continue
        trials, lower = cases * rule.trials, rule.expected - 0.05
        by_chance = chance_of_at_least(suite_at, trials, 1 - rule.expected)
        caught = chance_of_at_least(suite_at, trials, 1 - lower)
        lines.append(
            f"  {suite}: {suite_at} of {trials} ({cases} cases). Cases still passing {rule.expected:.0%} "
            f"of the time do that by chance {by_chance:.1%}\n  of the time, and with the case rule a "
            f"healthy {suite} suite fails the gate {healthy:.1%} of the time;\n  cases now passing "
            f"{lower:.0%} of the time are caught {caught:.0%} of the time."
        )
    print("\n".join(lines))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.gate")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="the rules can fail, and the record matches what the model is given")
    commands.add_parser("estimate", help="what one run of the gate sends, and what it would cost")
    run = commands.add_parser("run", help="run the gate against the record")
    run.add_argument("--real", action="store_true", help="call Anthropic's API; every call is billed")
    run.add_argument("--max-usd", type=float, metavar="DOLLARS", help="the most the run may spend")
    run.add_argument("--promote", action="store_true", help="on a pass, write evals/promoted.json")
    run.add_argument("--suite", choices=PARTS, help="run one part only (never a promotion)")
    run.add_argument("--vary", type=int, metavar="SEED", help="the mock stands in for a model that varies")
    run.add_argument("--trials", type=int, help="trials a case, instead of evals/gate.json's")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check()
    config = settings()
    if args.command == "estimate":
        print_estimate(
            estimate(PARTS, config.rule.trials, config.judge_trials), config.rule.trials, config.judge_trials
        )
        return 0
    if args.real and args.max_usd is None:
        parser.error(
            "--real is billed, so it needs a cap: add --max-usd DOLLARS "
            "(python -m helpdesk.gate estimate shows what a run costs)"
        )
    if args.max_usd is not None and args.max_usd <= 0:
        parser.error("--max-usd must be more than 0")
    if args.promote and (args.suite or args.vary is not None or args.trials):
        parser.error(
            "a promotion runs every part as evals/gate.json says: leave out --suite, --vary and --trials"
        )
    if args.vary is not None and args.real:
        parser.error("--vary only changes what the mock plays; leave it out with --real")
    if args.trials is not None and args.trials < 1:
        parser.error("--trials must be 1 or more")
    parts = (args.suite,) if args.suite else PARTS
    return run_gate(parts, args.real, args.vary, args.max_usd, args.promote, args.trials)


if __name__ == "__main__":
    sys.exit(main())
