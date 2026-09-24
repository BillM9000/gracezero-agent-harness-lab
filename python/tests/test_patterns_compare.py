"""The comparison of one agent against a team (chapter 14), and the policy check before any run."""

from __future__ import annotations

import subprocess
import sys

from helpdesk import patterns
from helpdesk.assistant.tools import passages_given
from helpdesk.services import access, citations


def measure(conn):
    return patterns.compare(conn, access.find_person(conn, "sam"))


def test_every_design_writes_the_same_drafts_and_saw_every_passage_they_cite(conn):
    # The comparison is fair only if each design did the same work from the same evidence.
    expected = patterns.drafts(patterns.IN_ORDER)
    for design, result in measure(conn).items():
        assert result.answer == expected, design
        given = {}
        for context in result.contexts:
            given |= passages_given(context.transcript)
        cited = set(citations.CITATION.findall(expected))
        assert cited <= set(given), f"{design}: never saw {sorted(cited - set(given))}"


def test_splitting_bounds_the_largest_request_and_costs_more_than_one_context_used_well(conn):
    all_at_once, ticket_by_ticket, team = (measure(conn)[d] for d in patterns.DESIGNS)
    assert (len(all_at_once.contexts), len(ticket_by_ticket.contexts), len(team.contexts)) == (1, 1, 6)
    assert (all_at_once.requests, ticket_by_ticket.requests, team.requests) == (3, 10, 13)
    # The team's largest request is under half of either single agent's...
    assert team.largest * 2 < min(all_at_once.largest, ticket_by_ticket.largest)
    # ...and it sends more than one agent that reads everything at once, less than one that goes
    # a ticket at a time and resends everything it has read on every turn.
    assert all_at_once.sent < team.sent < ticket_by_ticket.sent


def test_every_worker_request_repeats_its_system_prompt_and_tools(conn):
    team = measure(conn)[patterns.DESIGNS[2]]
    lead, *workers = team.contexts
    assert lead.name == "orchestrator"
    assert len({w.fixed for w in workers}) == 1
    assert all(size > w.fixed for w in workers for size in w.requests)


def test_the_comparison_prints_the_table_and_what_it_is_not():
    ran = subprocess.run(
        [sys.executable, "-m", "helpdesk.patterns", "compare"], capture_output=True, text=True
    )
    assert ran.returncode == 0, ran.stderr
    assert (
        "requests to the model                                3                  10                  13"
        in ran.stdout
    )
    assert "A real model takes its own path; measure that on a golden set" in ran.stdout


def test_nothing_runs_when_a_definition_breaks_the_policy(monkeypatch, tmp_path, capsys):
    # A policy that doesn't offer delegate_customer refuses the orchestrator, and nothing runs.
    policy = tmp_path / "policy.toml"
    text = patterns.POLICY.read_text(encoding="utf-8").replace(' "delegate_customer",', "")
    assert text != patterns.POLICY.read_text(encoding="utf-8")
    policy.write_text(text, encoding="utf-8")
    monkeypatch.setattr(patterns, "POLICY", policy)
    _, _, violations = patterns.definitions()
    assert violations == [
        """orchestrator.toml: tools[1]: "delegate_customer" isn't a tool the platform provides. """
        """The tools are "get_ticket", "find_tickets", "search_kb", "draft_reply", "close_ticket"."""
    ]
    monkeypatch.setattr(sys, "argv", ["helpdesk.patterns", "batch"])
    assert patterns.main() == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.rstrip().endswith("Nothing ran.")
