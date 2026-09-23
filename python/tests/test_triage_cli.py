"""The triage command line, run the way a reader runs it."""

from __future__ import annotations

import subprocess
import sys


def triage(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "helpdesk.triage", *args], capture_output=True, text=True)


def test_the_demo_runs_the_loop_to_an_answer():
    run = triage()
    assert run.returncode == 0, run.stderr
    assert 'turn 1  calls get_ticket {"ticket_id": 1}' in run.stdout
    assert 'turn 2  calls search_kb {"query": "password"}' in run.stdout
    assert "Reset emails can take up to ten minutes" in run.stdout
    assert run.stdout.rstrip().endswith("Finished in 3 turns (limit 6).")


def test_a_low_turn_limit_stops_the_demo_and_says_why():
    run = triage("--max-turns", "2")
    assert run.returncode == 1
    assert "Stopped: No answer after 2 turns" in run.stdout


def test_the_mock_refuses_a_question_it_has_no_script_for():
    run = triage("What is the capital of France?")
    assert run.returncode == 2
    assert "the mock only knows its demo script; add --real" in run.stderr
