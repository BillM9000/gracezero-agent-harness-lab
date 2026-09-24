"""The tools' command line, run the way a reader runs it (chapter 11)."""

from __future__ import annotations

import json
import subprocess
import sys

from helpdesk import tools as tools_cli
from helpdesk.services import access


def tools(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "helpdesk.tools", *args], capture_output=True, text=True)


def test_call_prints_what_the_model_would_get_back():
    run = tools("call", "get_ticket", "ticket_id=1")
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines()[:2] == [
        'get_ticket {"ticket_id": 1}, acting for Sam Rivera (support)',
        'result: Ticket 1 [open, high priority]: "Cannot reset my password"',
    ]


def test_call_refuses_what_the_person_cannot_see_and_exits_1():
    refused = tools("call", "get_ticket", "ticket_id=4")
    assert refused.returncode == 1
    assert "error: Sam Rivera can't see ticket 4:" in refused.stdout
    shown = tools("call", "get_ticket", "ticket_id=4", "--as", "dana")
    assert shown.returncode == 0
    assert 'result: Ticket 4 [closed, normal priority]: "App crashes on login"' in shown.stdout


def test_call_reads_json_values_and_takes_the_rest_as_text():
    assert tools_cli.argument_value("4") == 4
    assert tools_cli.argument_value("open") == "open"
    assert tools_cli.argument_value('"4"') == "4"
    run = tools("call", "get_ticket", "ticket_id=four")
    assert 'ticket_id must be a whole number, not "four"' in run.stdout
    assert tools("call", "get_ticket", "4").returncode == 2


def test_schema_prints_the_strict_form_the_adapter_sends():
    run = tools("schema", "find_tickets")
    assert run.returncode == 0, run.stderr
    sent = json.loads(run.stdout)
    assert sent["strict"] is True
    assert "minimum" not in sent["input_schema"]["properties"]["page"]


def test_list_shows_every_tool_and_what_the_definitions_cost():
    run = tools("list")
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith("The triage set: 3 tools, whose definitions are ")
    for line in ("get_ticket(ticket_id)  strict", "find_tickets(status?, assignee?, page?)  strict"):
        assert line in run.stdout
    assert tools("list", "--set", "narrow").stdout.startswith("The narrow set: 6 tools")


def test_both_sets_see_the_facts_each_task_needs(conn):
    # The comparison is fair only if both runs gathered what the answer rests on.
    measured = tools_cli.compare(conn, access.find_person(conn, "sam"))
    for task in tools_cli.TASKS:
        for which, run in measured[task.name].items():
            missing = [fact for fact in task.facts if fact not in run.results_text]
            assert not missing, f"{which}, {task.name}: missing {missing}"


def test_the_task_shaped_set_sends_less_for_every_task(conn):
    measured = tools_cli.compare(conn, access.find_person(conn, "sam"))
    for task in tools_cli.TASKS:
        narrow, triage = measured[task.name]["narrow"], measured[task.name]["triage"]
        assert triage.sent < narrow.sent, task.name
        assert triage.turns <= narrow.turns, task.name
    history = measured[tools_cli.TASKS[0].name]
    assert (history["narrow"].turns, history["narrow"].calls) == (3, 4)
    assert (history["triage"].turns, history["triage"].calls) == (2, 2)


def test_compare_prints_a_table_and_says_what_it_does_not_show():
    run = tools("compare")
    assert run.returncode == 0, run.stderr
    assert "narrow (6 tools)" in run.stdout and "triage (3 tools)" in run.stdout
    assert "Ticket 2, with the customer's history" in run.stdout
    assert "measure that on a golden set of tasks (chapter 21)" in run.stdout


def test_an_unknown_person_is_refused():
    run = tools("call", "get_ticket", "ticket_id=1", "--as", "bob")
    assert run.returncode == 2
    assert "No member of staff called 'bob'" in run.stderr
