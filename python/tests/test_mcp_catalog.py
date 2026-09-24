"""The catalog of approved MCP servers (chapter 13). Its fixtures are its specification.

Each file in tests/catalog_fixtures/ is a small catalog whose first comment lines say what the rules
must decide: `# expect: pass` or `# expect: fail`, and for a failure, `# reasons:` naming every
field they must flag. The test runs the real rules over every fixture and requires exactly those
fields, as chapter 18's policy tests do. The rest check the command, and the allowlist a host
enforces, which names each server by its address or command and never by its name.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import mcp_governance.__main__ as command
from mcp_governance import POLICY, SERVERS, load
from mcp_governance.catalog import RULES, allowlist, check

FIXTURES_DIR = Path(__file__).parent / "catalog_fixtures"
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
    assert len(FIXTURES) >= 20


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
    [violation] = check(load(FIXTURES_DIR / "fail-all-granting-scope.toml"), POLICY_DATA)
    assert violation.path == "servers[0].scopes[1]"
    assert violation.reason == (
        '"*" grants everything at once. Name what each scope allows, such as "tickets:read", so a token '
        "can carry only what a task needs."
    )


def test_the_organizations_catalog_passes(capsys):
    assert command.main([]) == 0
    assert capsys.readouterr().out.strip().endswith("1 catalog(s) against catalog/policy.toml: 0 problem(s).")


def test_a_run_that_finds_no_catalogs_fails(tmp_path, capsys):
    assert command.main(["check", str(tmp_path)]) == 2
    assert "nothing was checked" in capsys.readouterr().err


def test_the_allowlist_names_each_server_by_address_or_exact_command_never_by_name():
    two = load(FIXTURES_DIR / "pass-two-servers.toml")
    assert allowlist(two) == {
        "allowManagedMcpServersOnly": True,
        "allowedMcpServers": [
            {"serverUrl": "http://127.0.0.1:8765/mcp"},
            {"serverCommand": ["uvx", "example-notes-mcp==0.3.1"]},
        ],
    }


def test_the_allowlist_command_prints_the_catalog_as_a_host_enforces_it(capsys):
    assert command.main(["allowlist"]) == 0
    assert json.loads(capsys.readouterr().out) == allowlist(load(SERVERS))


def test_the_allowlist_command_refuses_a_catalog_that_breaks_the_rules(monkeypatch, capsys):
    monkeypatch.setattr(command, "SERVERS", FIXTURES_DIR / "fail-plain-http-elsewhere.toml")
    assert command.main(["allowlist"]) == 1
    assert capsys.readouterr().out == ""


def test_the_audit_command_prints_who_called_what_for_whom(tmp_path, capsys):
    log = tmp_path / "audit.jsonl"
    record = {
        "time": "2026-09-23T18:04:05+00:00",
        "client": "helpdesk-mcp-client",
        "person": "Sam Rivera (support)",
        "method": "tools/call",
        "name": "get_ticket",
        "arguments": {"ticket_id": 4},
        "outcome": "tool error",
    }
    log.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert command.main(["audit", "--log", str(log)]) == 0
    header, row = capsys.readouterr().out.splitlines()
    assert header.split() == ["time", "client", "for", "request", "outcome"]
    assert row == (
        "18:04:05  helpdesk-mcp-client  Sam Rivera (support)  "
        'tools/call get_ticket {"ticket_id": 4}  tool error'
    )
