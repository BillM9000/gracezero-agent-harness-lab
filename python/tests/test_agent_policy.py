"""The policy for agent definitions (chapter 18). Its fixtures are its specification.

Each file in tests/policy_fixtures/ is an agent definition whose first comment lines say what the
policy must decide: `# expect: pass` or `# expect: fail`, and for a failure, `# reasons:` naming
every field it must flag. The test runs the real policy over every fixture and requires exactly
those fields, no more and no fewer. The other tests check that the policy's data agrees with the
code it describes, and that the triage assistant refuses to run a definition that breaks it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import lab_sample
import pytest

from agent_policy import AGENTS, MODELS, POLICY, TODAY_VARIABLE, load
from agent_policy.__main__ import main
from agent_policy.rules import RULES, check, tracked
from helpdesk.assistant.proposing import WRITERS, assistant_tools, proposing_tools
from helpdesk.assistant.team import DELEGATE
from helpdesk.assistant.tools import triage_tools
from helpdesk.data.db import connect, init_schema
from helpdesk.model.cost import PRICES, provider_of
from helpdesk.services.access import APPROVERS, Person

FIXTURES_DIR = Path(__file__).parent / "policy_fixtures"
FIXTURES = sorted(FIXTURES_DIR.glob("*.toml"))
POLICY_DATA = load(POLICY)
MODELS_DATA = load(MODELS)
# The day the fixtures are checked as of, the same as conftest.py sets for the programs tests run.
TODAY = date(2026, 9, 24)


def expected(path: Path) -> tuple[str, set[str]]:
    text = path.read_text(encoding="utf-8")
    verdict = re.search(r"^# expect: (pass|fail)$", text, re.MULTILINE)
    assert verdict, f"{path.name} has no '# expect: pass' or '# expect: fail' line"
    reasons = re.search(r"^# reasons: (.+)$", text, re.MULTILINE)
    return verdict.group(1), {r.strip() for r in reasons.group(1).split(",")} if reasons else set()


def test_there_are_fixtures_to_run():
    # A glob that matched nothing would let every parametrized test below pass by never running.
    assert len(FIXTURES) >= 10


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_each_fixture_gets_exactly_the_verdict_it_names(path):
    verdict, reasons = expected(path)
    flagged = {violation.path for violation in check(load(path), POLICY_DATA, MODELS_DATA, TODAY)}
    if verdict == "pass":
        assert flagged == set()
    else:
        assert reasons, f"{path.name} expects a failure but names no reasons"
        assert flagged == reasons


def test_every_rule_is_shown_failing_by_some_fixture():
    shown = {
        violation.rule
        for path in FIXTURES
        for violation in check(load(path), POLICY_DATA, MODELS_DATA, TODAY)
    }
    assert shown == set(RULES)


def test_a_violation_names_the_field_the_reason_and_the_fix():
    [violation] = check(
        load(FIXTURES_DIR / "fail-too-many-tokens-for-the-model.toml"), POLICY_DATA, MODELS_DATA, TODAY
    )
    assert violation.path == "max_tokens"
    assert violation.reason == (
        "32,000 output tokens from claude-opus-5-5 could cost $0.64 a call, and the policy allows $0.32. "
        "Lower max_tokens to 16,000 or less, or use a cheaper approved model."
    )


def test_every_real_definition_passes(capsys):
    assert main([]) == 0
    assert "0 problem(s)" in capsys.readouterr().out


def test_a_run_that_finds_no_definitions_fails(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    assert "nothing was checked" in capsys.readouterr().err


def test_the_policy_prices_match_the_code():
    for model, entry in POLICY_DATA["models"].items():
        assert entry["output_usd_per_million"] == PRICES[model][1], model


def test_the_cost_tables_name_each_approved_models_provider_as_the_registry_does():
    # src/helpdesk/model/cost.py says whose pricing page each price came from, and agents/models.toml
    # whose deprecations page each date came from: the same provider, or one of them is wrong.
    registry = tracked(MODELS_DATA)
    for model in POLICY_DATA["models"]:
        assert provider_of(model) == registry[model]["provider_name"], model
    assert {provider_of(m) for m in POLICY_DATA["models"]} == {"Anthropic", "OpenAI"}


def test_the_policy_tools_are_the_tools_the_code_provides():
    conn = connect(":memory:")
    init_schema(conn)
    try:
        # Which tools exist doesn't depend on who the assistant acts for.
        provided = [spec.name for spec in triage_tools(conn, Person(1, "Any One", "support")).specs]
    finally:
        conn.close()
    # Chapter 14's orchestrator adds one tool of its own, and chapter 19 the two that write.
    assert sorted(POLICY_DATA["tools"]) == sorted([*provided, DELEGATE.name, *WRITERS])


def test_the_policy_names_exactly_the_tools_that_write_and_the_approvals_the_code_applies():
    # Chapter 19: [writes] must list every tool the code marks as writing, and no other, or a new
    # writer could be given to an agent without anyone naming whose approval it needs.
    conn = connect(":memory:")
    init_schema(conn)
    try:
        lead = Person(2, "Any One", "lead")
        readers = triage_tools(conn, lead)
        writers = proposing_tools(conn, lead, "any", {name: "lead" for name in WRITERS})
    finally:
        conn.close()
    assert readers.writers == ()
    assert sorted(writers.writers) == sorted(POLICY_DATA["writes"])
    assert POLICY_DATA["approvers"] == list(APPROVERS)
    assert set(POLICY_DATA["writes"].values()) <= set(APPROVERS)


def test_a_writer_left_out_of_approval_is_named_with_the_least_it_needs():
    [violation] = check(
        load(FIXTURES_DIR / "fail-writer-without-approval.toml"), POLICY_DATA, MODELS_DATA, TODAY
    )
    assert violation.path == "approval.close_ticket"
    assert violation.reason == (
        "missing. close_ticket changes things, so the definition must say whose approval a change needs "
        'before it happens: add close_ticket = "lead" under [approval], or a higher approval.'
    )


def test_the_triage_assistant_refuses_a_writer_without_an_approval_before_anything_runs():
    run = triage("--agent", str(FIXTURES_DIR / "fail-writer-without-approval.toml"))
    assert run.returncode == 2
    assert "approval.close_ticket: missing." in run.stderr
    assert run.stdout == ""


def test_the_tools_themselves_refuse_to_build_a_writer_without_an_approval():
    # The policy is checked before the assistant runs; the toolbox checks again, so code that skips
    # the policy still can't give an agent a tool that writes without saying whose approval it needs.
    conn = connect(":memory:")
    init_schema(conn)
    definition = load(FIXTURES_DIR / "fail-writer-without-approval.toml")
    try:
        with pytest.raises(ValueError, match="close_ticket change things"):
            assistant_tools(conn, Person(1, "Any One", "support"), definition)
    finally:
        conn.close()


def triage(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "helpdesk.triage", *args], capture_output=True, text=True)


def test_the_triage_assistant_refuses_a_definition_that_breaks_the_policy():
    run = triage("--agent", str(FIXTURES_DIR / "fail-model-not-approved.toml"))
    assert run.returncode == 2
    assert 'model: "claude-opus-4-1" isn\'t an approved model.' in run.stderr
    assert run.stderr.rstrip().endswith("Nothing ran.")
    assert run.stdout == ""


def test_the_triage_assistant_checks_the_turn_limit_it_is_given_too():
    run = triage("--max-turns", "50")
    assert run.returncode == 2
    assert "max_turns: 50 is more than the policy's limit of 10." in run.stderr


def test_the_real_definitions_live_in_the_agents_folder():
    assert (AGENTS / "triage.toml").exists()
    assert (AGENTS / "orchestrator.toml").exists()


# Chapter 20: models are components with a retirement date, kept in agents/models.toml.

READ = "(agents/models.toml, from Anthropic's model deprecations page, read 2026-09-24)"


APPROVED = '"claude-opus-5-5", "claude-sonnet-5", "gpt-6.1-sol"'


def test_an_unapproved_model_is_named_as_unapproved():
    [violation] = check(load(FIXTURES_DIR / "fail-model-not-approved.toml"), POLICY_DATA, MODELS_DATA, TODAY)
    assert (violation.rule, violation.reason) == (
        "model",
        f'"claude-opus-4-1" isn\'t an approved model. Use one of {APPROVED}, or ask '
        "the platform team to approve it in agents/policy.toml.",
    )


def test_a_retired_model_fails_with_its_date_and_what_to_move_to():
    violations = check(load(FIXTURES_DIR / "fail-model-retired.toml"), POLICY_DATA, MODELS_DATA, TODAY)
    retired = [v for v in violations if v.rule == "retired"]
    assert [v.rule for v in violations] == ["model", "retired"]
    assert retired[0].reason == (
        f"claude-opus-4-1-20250805 retired on 2026-08-05, and requests to it fail {READ}. Anthropic "
        f"recommends claude-opus-4-8 in its place, which isn't approved here: use one of {APPROVED}, or ask "
        "the platform team to approve it in agents/policy.toml."
    )


def test_an_approved_model_fails_the_day_its_earliest_retirement_is_within_the_notice():
    # claude-opus-5-5 may retire as soon as 2027-09-22, and the policy moves agents 90 days before.
    # No approved model has a later date; gpt-6.1-sol has none announced, so it's named, not suggested.
    triage_definition = load(AGENTS / "triage.toml")
    assert check(triage_definition, POLICY_DATA, MODELS_DATA, date(2027, 6, 23)) == []
    [violation] = check(triage_definition, POLICY_DATA, MODELS_DATA, date(2027, 6, 24))
    assert (violation.path, violation.rule) == ("model", "retiring")
    assert violation.reason == (
        "claude-opus-5-5 may retire as soon as 2027-09-22, in 90 days, and the policy moves agents 90 days "
        f'before {READ}. No approved model has a later retirement date announced, and "gpt-6.1-sol" has '
        "none announced: ask the platform team which to move to, or to approve a newer one."
    )


def test_a_model_that_retires_later_is_suggested_by_name():
    # On 2027-04-01 claude-sonnet-5 (2027-06-30) is inside the notice, and claude-opus-5-5 isn't.
    definition = {**load(AGENTS / "triage.toml"), "model": "claude-sonnet-5", "max_tokens": 16000}
    [violation] = check(definition, POLICY_DATA, MODELS_DATA, date(2027, 4, 1))
    assert violation.reason.endswith('Move to an approved model that retires later: "claude-opus-5-5".')


def test_the_policy_command_checks_as_of_the_day_it_is_given(capsys):
    # The lab's own definitions, whatever a reader has added beside them (tests/lab_sample.py).
    assert main([*(str(AGENTS / name) for name in lab_sample.DEFINITIONS), "--today", "2027-07-01"]) == 1
    out = capsys.readouterr().out
    assert "agents/triage.toml: model: claude-opus-5-5 may retire as soon as 2027-09-22, in 83 days" in out
    # One problem a definition on claude-opus-5-5: the triage assistant, the orchestrator and the
    # same-model judge (chapter 22). The second judge's model, gpt-6.1-sol, has no retirement announced.
    assert "agents/judge.toml: model: claude-opus-5-5 may retire as soon as 2027-09-22" in out
    assert "agents/judge-second.toml" not in out
    assert out.rstrip().endswith("as of 2027-07-01: 3 problem(s).")


def test_every_approved_model_is_in_the_registry_active_and_every_replacement_is_known():
    registry = tracked(MODELS_DATA)
    for model in POLICY_DATA["models"]:
        assert registry[model]["state"] == "active", model
    states = {"active", "legacy", "deprecated", "retired"}
    assert len(MODELS_DATA) >= 2, "the registry has a section for each provider the policy approves"
    for provider, section in MODELS_DATA.items():
        assert set(section) == {"name", "page", "source", "read", "models"}, provider
        assert isinstance(section["read"], date), provider
        for model, entry in section["models"].items():
            assert entry["state"] in states, model
            assert set(entry) <= {"state", "retires", "deprecated", "replacement"}, model
            # A retired model has the date it retired on. An active one has the earliest it may retire
            # only where its provider's page gives one; a deprecated one, where the date is announced.
            if entry["state"] == "retired":
                assert isinstance(entry["retires"], date), model
            if "retires" in entry:
                assert isinstance(entry["retires"], date), model
            if "replacement" in entry:
                assert entry["replacement"] in registry, model


def test_a_second_providers_dates_are_read_from_its_own_section():
    # gpt-5-2025-08-07: deprecated 2026-06-11, shut down 2026-12-11, replaced by gpt-5.6-sol (OpenAI's
    # deprecations page, read 2026-10-01). The report names that page and that day, not another's.
    violations = check(
        load(FIXTURES_DIR / "fail-second-provider-model-deprecated.toml"), POLICY_DATA, MODELS_DATA, TODAY
    )
    assert [v.rule for v in violations] == ["model", "retiring"]
    assert violations[1].reason == (
        "gpt-5-2025-08-07 is deprecated and retires on 2026-12-11, in 78 days (agents/models.toml, from "
        "OpenAI's deprecations page, read 2026-10-01). OpenAI recommends gpt-5.6-sol in its place, which "
        f"isn't approved here: use one of {APPROVED}, or ask the platform team to approve it in "
        "agents/policy.toml."
    )
    violations = check(
        load(FIXTURES_DIR / "fail-second-provider-model-retired.toml"), POLICY_DATA, MODELS_DATA, TODAY
    )
    assert [v.rule for v in violations] == ["model", "retired"]
    assert violations[1].reason.startswith(
        "gpt-5.2-chat-latest retired on 2026-08-10, and requests to it fail (agents/models.toml, from "
        "OpenAI's deprecations page, read 2026-10-01). OpenAI recommends gpt-5.6-sol in its place"
    )
    passing = load(FIXTURES_DIR / "pass-model-from-a-second-provider.toml")
    assert check(passing, POLICY_DATA, MODELS_DATA, TODAY) == []


def test_a_model_listed_under_two_providers_is_refused():
    twice = {
        **MODELS_DATA,
        "openai": {
            **MODELS_DATA["openai"],
            "models": {**MODELS_DATA["openai"]["models"], "claude-sonnet-5": {"state": "active"}},
        },
    }
    with pytest.raises(ValueError, match="lists claude-sonnet-5 under anthropic and openai"):
        tracked(twice)


def test_a_deprecated_model_fails_even_before_its_retirement_date_is_announced():
    violations = check(load(FIXTURES_DIR / "fail-model-deprecated.toml"), POLICY_DATA, MODELS_DATA, TODAY)
    assert [v.rule for v in violations] == ["model", "retiring"]
    assert violations[1].reason.startswith(
        f"claude-mythos-preview is deprecated, and its retirement date isn't announced yet {READ}. "
    )


def test_an_approved_model_nobody_tracks_fails_closed():
    section = MODELS_DATA["anthropic"]
    kept = {k: v for k, v in section["models"].items() if k != "claude-opus-5-5"}
    untracked = {**MODELS_DATA, "anthropic": {**section, "models": kept}}
    [violation] = check(load(AGENTS / "triage.toml"), POLICY_DATA, untracked, TODAY)
    assert (violation.rule, violation.reason) == (
        "model",
        '"claude-opus-5-5" is approved but isn\'t in agents/models.toml, so nothing tracks when it retires. '
        "Add it under its provider's section, from that provider's deprecations page.",
    )


def test_the_triage_assistant_refuses_a_model_near_retirement_before_anything_runs():
    # conftest.py fixes the day for every program a test starts; here the day is moved on.
    env = {**os.environ, TODAY_VARIABLE: "2027-07-01"}
    run = subprocess.run([sys.executable, "-m", "helpdesk.triage"], capture_output=True, text=True, env=env)
    assert run.returncode == 2
    assert "model: claude-opus-5-5 may retire as soon as 2027-09-22, in 83 days" in run.stderr
    assert run.stdout == ""
