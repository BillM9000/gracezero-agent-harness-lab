"""The policy for agent definitions (chapter 18). Its fixtures are its specification.

Each file in tests/policy_fixtures/ is an agent definition whose first comment lines say what the
policy must decide: `# expect: pass` or `# expect: fail`, and for a failure, `# reasons:` naming
every field it must flag. The test runs the real policy over every fixture and requires exactly
those fields, no more and no fewer. The other tests check that the policy's data agrees with the
code it describes, and that the triage assistant refuses to run a definition that breaks it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from agent_policy import AGENTS, POLICY, load
from agent_policy.__main__ import main
from agent_policy.rules import RULES, check
from helpdesk.assistant.team import DELEGATE
from helpdesk.assistant.tools import triage_tools
from helpdesk.data.db import connect, init_schema
from helpdesk.model.cost import PRICES
from helpdesk.services.access import Person

FIXTURES_DIR = Path(__file__).parent / "policy_fixtures"
FIXTURES = sorted(FIXTURES_DIR.glob("*.toml"))
POLICY_DATA = load(POLICY)


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
    flagged = {violation.path for violation in check(load(path), POLICY_DATA)}
    if verdict == "pass":
        assert flagged == set()
    else:
        assert reasons, f"{path.name} expects a failure but names no reasons"
        assert flagged == reasons


def test_every_rule_is_shown_failing_by_some_fixture():
    shown = {violation.rule for path in FIXTURES for violation in check(load(path), POLICY_DATA)}
    assert shown == set(RULES)


def test_a_violation_names_the_field_the_reason_and_the_fix():
    [violation] = check(load(FIXTURES_DIR / "fail-too-many-tokens-for-the-model.toml"), POLICY_DATA)
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


def test_the_policy_tools_are_the_tools_the_code_provides():
    conn = connect(":memory:")
    init_schema(conn)
    try:
        # Which tools exist doesn't depend on who the assistant acts for.
        provided = [spec.name for spec in triage_tools(conn, Person(1, "Any One", "support")).specs]
    finally:
        conn.close()
    # Chapter 14's orchestrator adds one tool of its own.
    assert sorted(POLICY_DATA["tools"]) == sorted([*provided, DELEGATE.name])


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
