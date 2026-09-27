"""The triage command line, run the way a reader runs it."""

from __future__ import annotations

import subprocess
import sys

from helpdesk import triage as triage_cli
from helpdesk.assistant.agent import run_agent
from helpdesk.assistant.tools import triage_tools
from helpdesk.model.mock import MockModel
from helpdesk.model.types import ModelResponse
from helpdesk.services import kb


def triage(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "helpdesk.triage", *args], capture_output=True, text=True)


def test_the_demo_runs_the_loop_to_an_answer():
    run = triage()
    assert run.returncode == 0, run.stderr
    assert 'turn 1  calls get_ticket {"ticket_id": 1}' in run.stdout
    assert 'turn 2  calls search_kb {"query": "reset email never arrives"}' in run.stdout
    assert "Reset emails can take up to ten minutes" in run.stdout
    assert "Finished in 3 turns (limit 6)." in run.stdout


def test_the_demo_answer_cites_only_what_it_was_given_and_every_citation_holds():
    run = triage()
    assert run.returncode == 0, run.stderr
    assert (
        "Citations: 3 checked against the passages this run was given (1#2, 1#3, 11#2); all exist "
        "and use only their passages' words." in run.stdout
    )
    assert run.stdout.rstrip().endswith("Not checked: 2 sentence(s) cite nothing.")


def test_a_draft_that_changes_what_its_passage_says_is_stopped(conn, capsys):
    script = [
        *triage_cli.DEMO_SCRIPT[:2],
        ModelResponse("end_turn", text="Reset emails can take up to an hour [1#2]."),
    ]
    run = run_agent(MockModel(script), triage_tools(conn), system="s", task=triage_cli.DEMO_TASK)
    known = {chunk.id for chunk in kb.build_index(conn).chunks}
    assert not triage_cli.report_citations(run.answer, run.transcript, known)
    assert "[1#2] doesn't say: hour" in capsys.readouterr().out


def test_a_low_turn_limit_stops_the_demo_and_says_why():
    run = triage("--max-turns", "2")
    assert run.returncode == 1
    assert "Stopped: No answer after 2 turns" in run.stdout


def test_the_mock_refuses_a_question_it_has_no_script_for():
    run = triage("What is the capital of France?")
    assert run.returncode == 2
    assert "the mock only knows its demo script; add --real" in run.stderr
