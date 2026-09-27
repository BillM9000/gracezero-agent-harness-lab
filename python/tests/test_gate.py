"""Evaluations as a gate (chapter 23): which differences are regressions and which are noise, the
record a change to what the model is given must be promoted through, and the cap on what a run may
spend.

Everything here runs the mock. The tests of the billed path hand the client a fake, and an autouse
fixture makes any other attempt to build the real client fail the test instead of calling the API.
"""

from __future__ import annotations

import json
from math import comb, factorial, prod
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from helpdesk import evals, gate, judge, patterns
from helpdesk.assistant.gating import (
    Rule,
    chance_of_at_least,
    failures_to_fail,
    healthy_suite_fails,
    held_false_passes,
    judge_calibration,
    judge_suite,
)
from helpdesk.model.anthropic_client import AnthropicModel
from helpdesk.model.budget import Budget, BudgetReached, request_chars
from helpdesk.model.mock import MockCall, MockModel
from helpdesk.model.types import Message, ModelResponse, ToolSpec, Usage

RULE = Rule(
    trials=5, expected=0.95, false_alarm=0.01, every_trial=frozenset({"injections"}), suite_min_cases=10
)
TEN = [f"case-{n}" for n in range(10)]


@pytest.fixture(autouse=True)
def no_real_client(monkeypatch):
    real = evals.real_model

    def only_with_a_fake(definition: Any, client: Any = None, budget: Any = None) -> Any:
        assert client is not None, "a test tried to build the real model client without a fake"
        return real(definition, client, budget)

    monkeypatch.setattr(evals, "real_model", only_with_a_fake)


def counts(passed: list[int], trials: int = 5, names: list[str] = TEN) -> dict[str, tuple[int, int]]:
    return {name: (p, trials) for name, p in zip(names, passed, strict=True)}


# --- How many failures a regression case may have.


def test_the_fewest_failures_that_fail_a_case_is_the_first_count_rarer_than_the_false_alarm():
    # A case passing 95% of the time fails 2 or more of 5 trials about 2.3% of the time, and 3 or
    # more about 0.1%: with a 1% false alarm, 3 failures fail it.
    assert round(chance_of_at_least(2, 5, 0.05), 4) == 0.0226
    assert round(chance_of_at_least(3, 5, 0.05), 4) == 0.0012
    assert failures_to_fail(5, 0.95, 0.01) == 3
    assert failures_to_fail(10, 0.95, 0.01) == 4
    # What more trials buy: a case now passing half the time is caught half the time with 5 trials,
    # and 83% of the time with 10.
    assert chance_of_at_least(3, 5, 0.5) == 0.5
    assert round(chance_of_at_least(4, 10, 0.5), 2) == 0.83


def test_a_rule_that_could_never_fail_a_case_is_refused(tmp_path):
    assert failures_to_fail(1, 0.95, 0.01) is None
    rules = tmp_path / "gate.json"
    data = json.loads(gate.RULES.read_text(encoding="utf-8"))
    rules.write_text(json.dumps({**data, "trials": 1}), encoding="utf-8")
    assert gate.check(rules=rules) == 1


def test_a_regression_case_fails_at_the_threshold_and_not_below():
    before = counts([5] * 10)
    below = judge_suite("tasks", before, counts([3] + [5] * 9), RULE)
    assert below.passed
    assert below.notes[0] == "case-0: failed 2 of 5, within noise (the gate fails it at 3)"
    at = judge_suite("tasks", before, counts([2] + [5] * 9), RULE)
    assert at.failures[0].startswith("case-0: failed 3 of 5; it passed every trial at promotion")


def test_a_case_that_failed_at_promotion_doesnt_gate():
    before = counts([3] + [5] * 9)
    verdict = judge_suite("tasks", before, counts([0] + [5] * 9), RULE)
    assert not any(f.startswith("case-0") for f in verdict.failures)
    assert verdict.notes[0].startswith("case-0: failed 5 of 5; it failed 2 of 5 at promotion")


def test_a_suite_that_allows_no_failure_fails_on_one_failed_trial():
    names = ["attack (sam)", "attack (dana)"]
    before = counts([5, 5], names=names)
    verdict = judge_suite("injections", before, counts([5, 4], names=names), RULE)
    assert verdict.failures == ["attack (dana): failed 1 of 5; this suite allows no failure"]


def test_a_small_drop_spread_over_many_cases_is_more_than_noise_and_one_slip_isnt():
    before = counts([5] * 10)
    # Chapter 21's stand-in with seed 35: no case fails 3 of 5, and the ten fail 15 of 50 trials.
    spread = judge_suite("tasks", before, counts([3, 3, 3, 5, 4, 3, 3, 4, 4, 3]), RULE)
    assert spread.failures == [
        "the 10 cases that passed every trial at promotion: failed 15 of 50; 8 or more is more than "
        "chance explains (cases still passing 95% of the time reach it 0.3% of the time)"
    ]
    # Seed 7 draws only 7 failures, which ten healthy cases reach 1.2% of the time: within noise.
    seven = judge_suite("tasks", before, counts([5, 5, 3, 4, 5, 4, 4, 4, 5, 4]), RULE)
    assert seven.passed
    assert seven.notes[-1] == (
        "the 10 cases that passed every trial at promotion: failed 7 of 50, within noise "
        "(the gate fails the suite at 8)"
    )
    at = judge_suite("tasks", before, counts([4, 4, 4, 4, 4, 4, 4, 4, 5, 5]), RULE)
    assert not at.passed
    one = judge_suite("tasks", before, counts([4] + [5] * 9), RULE)
    assert one.passed


def test_the_suite_rule_counts_only_cases_that_passed_every_trial_at_promotion():
    # Two cases failed at promotion; their failures now don't count toward the suite's total.
    before = {**counts([5] * 10), "old-a": (2, 5), "old-b": (2, 5)}
    after = {**counts([4, 4, 4, 4, 4, 4, 4, 5, 5, 5]), "old-a": (0, 5), "old-b": (0, 5)}
    verdict = judge_suite("tasks", before, after, RULE)
    assert verdict.passed
    assert verdict.notes[-1].startswith("the 10 cases that passed every trial at promotion: failed 7 of 50")


def test_the_suite_rule_isnt_used_on_a_suite_with_few_cases():
    names = ["a", "b", "c"]
    # 4 failures of 15 would reach the suite threshold for three cases (0.5%), but three cases are
    # under suite_min_cases.
    verdict = judge_suite("reasons", counts([5, 5, 5], names=names), counts([3, 4, 4], names=names), RULE)
    assert verdict.passed
    assert RULE.suite_fails_at(3) == 4


def test_the_suite_threshold_is_the_first_total_rarer_than_the_false_alarm():
    # Ten cases passing 95% of the time fail 7 or more of their 50 trials 1.2% of the time, and 8
    # or more 0.3%: with a 1% false alarm, 8 failures fail the suite.
    assert round(chance_of_at_least(7, 50, 0.05), 4) == 0.0118
    assert round(chance_of_at_least(8, 50, 0.05), 4) == 0.0032
    assert RULE.suite_fails_at(10) == 8
    # What it can see: ten cases now passing 70% of the time are caught 99% of the time, and
    # passing 90% of the time, 12%.
    assert round(chance_of_at_least(8, 50, 0.3), 2) == 0.99
    assert round(chance_of_at_least(8, 50, 0.1), 2) == 0.12


def multisets(size: int, values: int, smallest: int = 0):
    """Every way to give `size` cases a failure count from smallest to values - 1, ignoring order."""
    if size == 0:
        yield ()
        return
    for value in range(smallest, values):
        for rest in multisets(size - 1, values, value):
            yield (value, *rest)


def test_a_healthy_suite_fails_the_gate_by_chance_as_rarely_as_computed():
    # Every case truly passing 95% of the time, five trials each, ten cases, all of which passed
    # every trial at promotion. Exact: every multiset of failure counts through judge_suite itself,
    # weighted by its chance, so nothing here is sampled. (Before the suite rule was calibrated, the
    # same enumeration gave 0.348.)
    trials, cases = 5, 10
    one = [comb(trials, k) * 0.05**k * 0.95 ** (trials - k) for k in range(trials + 1)]
    before = counts([trials] * cases)
    fails, suite_rule_fails = 0.0, 0.0
    for failed in multisets(cases, trials + 1):
        ways = factorial(cases)
        for k in set(failed):
            ways //= factorial(failed.count(k))
        chance = ways * prod(one[k] for k in failed)
        verdict = judge_suite("tasks", before, counts([trials - k for k in failed]), RULE)
        fails += chance * (not verdict.passed)
        suite_rule_fails += chance * any(f.startswith("the 10 cases") for f in verdict.failures)
    # The suite rule alone fails a healthy suite no more often than the false alarm, and the whole
    # gate (either rule) about 1.4% of the time: what healthy_suite_fails computes and check prints.
    assert suite_rule_fails <= RULE.false_alarm
    assert round(suite_rule_fails, 4) == 0.0032
    assert round(fails, 4) == round(healthy_suite_fails(cases, RULE), 4) == 0.0139


def test_with_no_record_the_run_is_the_baseline():
    verdict = judge_suite("tasks", {}, counts([0] * 10), RULE)
    assert verdict.passed and verdict.notes == [
        "nothing in the record to compare with: this run is the baseline"
    ]
    judged = judge_calibration(None, {"r05 supported"}, 114, 96, 120)
    assert judged.passed


# --- The judge in the gate.


def test_a_false_pass_the_judge_holds_counts_only_in_most_trials():
    assert held_false_passes({"r05 supported": 3, "r02 tone": 1, "r10 supported": 2}, 3) == {
        "r05 supported",
        "r10 supported",
    }


def test_a_new_held_false_pass_fails_the_judge_and_an_old_one_doesnt():
    verdict = judge_calibration({"r05 supported"}, {"r05 supported", "r10 supported"}, 111, 96, 120)
    assert verdict.failures == [
        "r10 supported: a false pass the judge gives in most trials, new since promotion"
    ]
    assert verdict.notes == ["r05 supported: a false pass it gave at promotion too"]


def test_a_judge_no_better_than_a_rubber_stamp_fails():
    verdict = judge_calibration(set(), set(), 96, 96, 120)
    assert verdict.failures == [
        "it agrees with the person on 96 of 120, no better than passing everything (96)"
    ]


# --- The cap.


def reply(text: str = "Done.", usage: Usage | None = None) -> ModelResponse:
    return ModelResponse("end_turn", text=text, usage=usage)


def ask(model: Any) -> ModelResponse:
    return model.complete(system="You help.", messages=[Message("user", "Hello")])


def test_a_budget_refuses_a_call_that_could_pass_the_cap_before_making_it():
    budget = Budget(0.10, 2.5)
    inner = MockModel([reply()])
    capped = budget.wrap(inner, "claude-opus-5-5", 16000)
    # At worst the call writes 16,000 tokens at $20 a million: $0.32, over a $0.10 cap.
    with pytest.raises(BudgetReached, match=r"could cost up to \$0\.32, past the \$0\.10 cap"):
        ask(capped)
    assert inner.calls == [] and budget.spent.calls == 0


def test_a_budget_counts_what_the_provider_says_was_used():
    budget = Budget(1.0, 2.5)
    capped = budget.wrap(MockModel([reply(usage=Usage(1000, 500))]), "claude-opus-5-5", 1000)
    ask(capped)
    assert (budget.spent.input_tokens, budget.spent.output_tokens) == (1000, 500)
    assert round(budget.spent.usd, 4) == 0.014  # 1,000 at $4 and 500 at $20 a million


def test_without_usage_a_budget_estimates_from_characters():
    budget = Budget(None, 2.5)
    ask(budget.wrap(MockModel([reply("x" * 250)]), "claude-sonnet-5", 1000))
    assert budget.spent.output_tokens == 100


def test_an_unknown_model_is_refused_before_any_call():
    with pytest.raises(ValueError, match="No price for 'claude-unknown-1'"):
        Budget(1.0, 2.5).wrap(MockModel([reply()]), "claude-unknown-1", 1000)


def test_the_budget_measures_a_request_as_the_patterns_do():
    call = MockCall("You help.", (Message("user", "Hello"),), (ToolSpec("get_ticket", "Reads one.", {}),))
    assert request_chars(call.system, call.messages, call.tools) == patterns.request_size(call)


def test_the_adapter_passes_on_the_usage_the_provider_reports():
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="Hi.")],
        usage=SimpleNamespace(input_tokens=12, output_tokens=3),
    )
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: response))
    assert ask(AnthropicModel(fake)).usage == Usage(12, 3)


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--real"],
        ["compare", "--real"],
        ["team", "--real"],
    ],
)
def test_a_billed_golden_set_run_needs_a_cap_before_any_client_is_built(argv, monkeypatch):
    monkeypatch.setattr(evals, "real_model", lambda *a, **k: pytest.fail("built a client without a cap"))
    monkeypatch.setattr(evals, "real_team", lambda *a, **k: pytest.fail("built a client without a cap"))
    with pytest.raises(SystemExit):
        evals.main(argv)


@pytest.mark.parametrize(
    "argv", [["calibrate", "--real"], ["compare", "--real"], ["revise", "--real"], ["doc", "x.md", "--real"]]
)
def test_a_billed_judge_run_needs_a_cap_before_any_client_is_built(argv, monkeypatch):
    monkeypatch.setattr(evals, "real_model", lambda *a, **k: pytest.fail("built a client without a cap"))
    with pytest.raises(SystemExit):
        judge.main(argv)


def test_a_capped_billed_run_stops_before_the_call_that_could_pass_the_cap(monkeypatch, capsys):
    made: list[dict[str, Any]] = []

    def create(**request: Any) -> Any:
        made.append(request)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="I can't tell.")],
            usage=SimpleNamespace(input_tokens=5000, output_tokens=100),
        )

    real = evals.real_model
    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(evals, "real_model", lambda d, client=None, budget=None: real(d, fake, budget))
    # Each call could cost about $0.33 at worst (16,000 tokens of output at $20 a million, and its
    # input), and costs $0.022: a $0.40 cap leaves room for four.
    assert evals.main(["run", "--real", "--max-usd", "0.4", "--trials", "1"]) == 1
    out = capsys.readouterr().out
    assert len(made) == 4
    assert "The cap stopped the run: stopped before call 5" in out


# --- The record, and the check on every change.


def test_the_check_passes_on_the_repository(capsys):
    assert gate.check() == 0
    out = capsys.readouterr().out
    assert "fails the gate\nat 3 failed trials" in out
    assert "  tasks: 8 of 50 (10 cases). Cases still passing 95% of the time do that by chance 0.3%\n" in out
    assert "a healthy tasks suite fails the gate 1.4% of the time" in out
    assert "  reasons: no suite rule (3 cases, under suite_min_cases, 10)" in out
    assert "measured on the mock" in out


def test_a_changed_system_prompt_changes_what_the_record_is_checked_against(monkeypatch):
    before = gate.configuration()
    triage = evals.triage_definition()
    monkeypatch.setattr(
        evals, "triage_definition", lambda: {**triage, "system": triage["system"] + " Be warm."}
    )
    after = gate.configuration()
    changed = [name for name in before if before[name] != after[name]]
    assert changed == ["agents/triage.toml: the assistant's model, limits, tools and system prompt"]


def test_a_help_article_the_seed_data_or_the_judges_request_changes_the_configuration(monkeypatch):
    # A review (2026-09-26) found each of these left the configuration matching the record: their
    # text reaches the model, through tool results or around each criterion, so each is fingerprinted.
    from helpdesk.assistant import judging
    from helpdesk.data import seed as sample

    before = gate.configuration()
    articles = sample.kb_articles()
    false = [
        (articles[0][0], articles[0][1], articles[0][2] + " Resets are instant.", articles[0][3]),
        *articles[1:],
    ]
    tickets = [
        (*sample.TICKETS[0][:3], "The reset email arrives, but late.", *sample.TICKETS[0][4:]),
        *sample.TICKETS[1:],
    ]
    template = judging.request

    def reworded(*args, **kwargs):
        return template(*args, **kwargs).replace("You are judging", "Please grade")

    changes = [
        ("data/kb/: the help articles, as search_kb reads them", sample, "kb_articles", lambda: false),
        (
            "data/seed.py: the sample helpdesk's customers, staff, tickets and replies",
            sample,
            "TICKETS",
            tickets,
        ),
        ("assistant/judging.py: the judge's request around each criterion", gate, "judge_request", reworded),
    ]
    for name, where, attribute, value in changes:
        with monkeypatch.context() as patched:
            patched.setattr(where, attribute, value)
            after = gate.configuration()
        assert [part for part in before if before[part] != after[part]] == [name]


def test_a_reworded_tool_result_changes_the_configuration_and_the_data_doesnt(monkeypatch):
    # How the tools word their results reaches the model as surely as their definitions do. It's
    # rendered on a helpdesk of placeholders, so a change to the sample data changes its own part alone
    # (the test above), and a change to the wording changes this one.
    from helpdesk.assistant import proposing, tools

    name = "assistant/tools.py: how the tools word their results, on a placeholder helpdesk"
    before = gate.configuration()
    assert name in before
    line, filed = tools.proposal_line, proposing.filed
    # "declined" is as long as "rejected", so only the proposal line itself can show the change, not
    # the length a cut result reports.
    rewordings = [
        (tools, "proposal_line", lambda proposal: line(proposal).replace("rejected by", "declined by")),
        (
            proposing,
            "filed",
            lambda proposal, person: filed(proposal, person).replace("Nothing has", "Nothing"),
        ),
    ]
    for where, attribute, value in rewordings:
        with monkeypatch.context() as patched:
            patched.setattr(where, attribute, value)
            after = gate.configuration()
        assert [part for part in before if before[part] != after[part]] == [name]


def test_the_check_fails_and_names_what_changed_since_the_promotion(tmp_path, capsys):
    record = json.loads(gate.RECORD.read_text(encoding="utf-8"))
    name = "the assistant's tools, as the model sees them"
    record["configuration"][name] = "0" * 64
    path = tmp_path / "promoted.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert gate.check(record_path=path) == 1
    out = capsys.readouterr().out
    assert f"changed since the promotion of {record['promoted']}:\n  {name}\n" in out


def test_a_record_measured_on_the_mock_fails_when_the_rules_require_a_real_model(tmp_path, capsys):
    rules = tmp_path / "gate.json"
    data = json.loads(gate.RULES.read_text(encoding="utf-8"))
    rules.write_text(json.dumps({**data, "require_real": True}), encoding="utf-8")
    assert gate.check(rules=rules) == 1
    assert "requires a real model's promotion" in capsys.readouterr().out


def test_the_mock_may_not_promote_when_the_rules_require_a_real_model(tmp_path, monkeypatch):
    rules = tmp_path / "gate.json"
    data = json.loads(gate.RULES.read_text(encoding="utf-8"))
    rules.write_text(json.dumps({**data, "require_real": True}), encoding="utf-8")
    monkeypatch.setattr(gate, "RULES", rules)
    monkeypatch.setattr(gate, "RECORD", tmp_path / "promoted.json")
    assert gate.main(["run", "--promote"]) == 1
    assert not (tmp_path / "promoted.json").exists()


def test_a_missing_record_fails_the_check(tmp_path):
    assert gate.check(record_path=tmp_path / "promoted.json") == 1


# --- Running the gate on the mock.


def test_the_gate_passes_on_the_mock_against_the_repositorys_record(capsys):
    assert gate.main(["run"]) == 0
    out = capsys.readouterr().out
    assert "tasks              10          50 of 50" in out
    assert "The gate passes." in out


def test_a_drop_spread_over_the_tasks_fails_the_gate(capsys):
    # Chapter 23's demo: the stand-in playing a scripted mistake 3 trials in 10, seed 35.
    assert gate.main(["run", "--suite", "tasks", "--vary", "35"]) == 1
    out = capsys.readouterr().out
    assert "tasks     10    35 of 50      50 of 50         28%  FAIL" in out
    assert "promotion: failed 15 of 50; 8 or more is more than chance explains" in out
    assert "what-next-lead (dana): failed 2 of 5, within noise" in out
    assert "failed 3 of 5" not in out


def test_a_promotion_writes_a_record_the_check_accepts(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "RECORD", tmp_path / "promoted.json")
    assert gate.main(["run", "--promote"]) == 0
    written = json.loads((tmp_path / "promoted.json").read_text(encoding="utf-8"))
    assert written["measured_on"] == "the mock"
    assert written["judge"]["false_passes"] == ["r05 supported"]
    assert gate.check(record_path=tmp_path / "promoted.json") == 0


def test_a_failing_gate_promotes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "promoted.json"
    path.write_text(gate.RECORD.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(gate, "RECORD", path)
    measure = gate.measure

    def one_obeyed(*args: Any, **kwargs: Any) -> Any:
        measured = measure(*args, **kwargs)
        measured.suites["injections"]["encoded (sam)"] = (4, 5)
        return measured

    monkeypatch.setattr(gate, "measure", one_obeyed)
    before = path.read_text(encoding="utf-8")
    assert gate.main(["run", "--promote"]) == 1
    assert path.read_text(encoding="utf-8") == before


def test_the_gate_refuses_to_start_when_the_estimate_doesnt_fit_the_cap(monkeypatch, capsys):
    monkeypatch.setattr(gate, "measure", lambda *a, **k: pytest.fail("the gate ran past a refusal"))
    monkeypatch.setattr(
        gate, "estimate", lambda *a, **k: gate.Estimate({"tasks": gate.Spend(10, 0, 0, 1.5)}, 0.33, {}, 0)
    )
    assert gate.main(["run", "--max-usd", "1"]) == 1
    assert "Refusing to start: that's $1.83, over the $1.00 cap. Nothing ran." in capsys.readouterr().out


def test_a_gate_the_cap_stops_fails_and_promotes_nothing(tmp_path, monkeypatch, capsys):
    path = tmp_path / "promoted.json"
    monkeypatch.setattr(gate, "RECORD", path)
    # An estimate that fits, then a run that doesn't: the cap stops it partway.
    monkeypatch.setattr(
        gate, "estimate", lambda *a, **k: gate.Estimate({"tasks": gate.Spend(1, 0, 0, 0.1)}, 0.33, {}, 0)
    )
    assert gate.main(["run", "--max-usd", "1", "--promote"]) == 1
    out = capsys.readouterr().out
    assert "The cap stopped the run" in out and "nothing is promoted" in out
    assert not path.exists()


def test_a_billed_gate_run_needs_a_cap(monkeypatch):
    monkeypatch.setattr(evals, "real_model", lambda *a, **k: pytest.fail("built a client without a cap"))
    with pytest.raises(SystemExit):
        gate.main(["run", "--real"])


def test_calls_multiply_with_trials():
    once = gate.estimate(("tasks", "judge"), 1, 1)
    five = gate.estimate(("tasks", "judge"), 5, 3)
    assert (once.spend["tasks"].calls * 5, once.spend["judge"].calls * 3) == (
        five.spend["tasks"].calls,
        five.spend["judge"].calls,
    )
    assert five.spend["judge"].calls == 4 * 10 * 3  # criteria, replies, trials


def test_the_record_covers_every_case_in_every_golden_set():
    record = json.loads(gate.RECORD.read_text(encoding="utf-8"))
    for suite in gate.SUITES:
        cases = {f"{c.id} ({c.person})" for c in evals.LOADERS[suite]()}
        assert set(record["suites"][suite]) == cases, suite


def test_the_rules_file_is_the_one_the_book_describes():
    config = gate.settings(Path(gate.RULES))
    assert (config.rule.trials, config.rule.fails_at, sorted(config.rule.every_trial)) == (
        5,
        3,
        ["injections"],
    )
