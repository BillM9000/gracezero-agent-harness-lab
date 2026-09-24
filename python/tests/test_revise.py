"""Evaluator and optimizer (chapter 14): a draft goes back until the check passes, never forever."""

from __future__ import annotations

import subprocess
import sys

from helpdesk import patterns
from helpdesk.assistant.revise import feedback, revise
from helpdesk.assistant.tools import triage_tools
from helpdesk.model.mock import MockModel
from helpdesk.model.types import ModelResponse
from helpdesk.services import access, citations

WRONG = patterns.REVISE_SCRIPT[1].text  # "up to an hour", where the passage says ten minutes
RIGHT = patterns.REVISE_SCRIPT[2].text


def run(conn, script, **limits):
    tools = triage_tools(conn, access.find_person(conn, "sam")).only(["get_ticket", "search_kb"])
    model = MockModel(script)
    result = revise(
        model,
        tools,
        system="Draft replies.",
        task=patterns.REVISE_TASK,
        known=patterns.known_passages(conn),
        **limits,
    )
    return model, result


def wrong(n: int) -> ModelResponse:
    """A failing draft that differs each round, so only the round limit can stop it."""
    return ModelResponse("end_turn", text=f"{WRONG} Draft {n}.")


def test_a_draft_that_fails_the_check_goes_back_and_the_revision_is_accepted(conn):
    model, result = run(conn, patterns.REVISE_SCRIPT)
    assert [d.report.ok for d in result.drafts] == [False, True]
    assert result.stopped == "passed" and result.accepted
    assert result.answer == RIGHT
    assert len(model.calls) == 3


def test_the_revision_request_carries_the_problem_the_check_found(conn):
    model, _ = run(conn, patterns.REVISE_SCRIPT)
    sent_back = model.calls[2].messages[-1].content
    assert sent_back.startswith("The citation check found 1 problem(s) in your draft:")
    assert "[1#2] doesn't say: hour" in sent_back


def test_each_round_continues_the_same_conversation(conn):
    model, _ = run(conn, patterns.REVISE_SCRIPT)
    # The revision sees the task, its tool calls and results, its first draft and the feedback.
    roles = [(m.role, m.content[:15]) for m in model.calls[2].messages]
    assert roles[0] == ("user", patterns.REVISE_TASK[:15])
    assert ("assistant", WRONG[:15]) in roles
    assert roles[-1] == ("user", "The citation ch")


def test_a_drafter_that_never_fixes_it_stops_at_the_round_limit(conn):
    # Six failing drafts are scripted; the limit must stop the loop after three.
    script = [patterns.REVISE_SCRIPT[0], *[wrong(n) for n in range(1, 7)]]
    model, result = run(conn, script, max_rounds=3)
    assert result.stopped == "limit" and not result.accepted
    assert len(result.drafts) == 3
    assert len(model.calls) == 4


def test_an_unchanged_draft_stops_the_loop_before_the_limit(conn):
    script = [
        patterns.REVISE_SCRIPT[0],
        ModelResponse("end_turn", text=WRONG),
        ModelResponse("end_turn", text=WRONG),
    ]
    _, result = run(conn, script, max_rounds=5)
    assert result.stopped == "unchanged" and not result.accepted
    assert len(result.drafts) == 2


def test_the_feedback_names_every_problem_and_what_to_do():
    report = citations.check(
        "It takes an hour [1#2]. It costs money [1#9].",
        {"1#2": "Reset emails can take up to ten minutes to arrive."},
        {"1#2"},
    )
    text = feedback(report)
    assert text.startswith("The citation check found 2 problem(s)")
    assert "[1#9] doesn't exist in the knowledge base" in text
    assert text.endswith("Reply with the whole draft again.")


def patterns_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "helpdesk.patterns", *args], capture_output=True, text=True)


def test_the_demo_is_accepted_on_the_second_round():
    ran = patterns_cli("revise")
    assert ran.returncode == 0, ran.stderr
    assert "  [1#2] doesn't say: hour" in ran.stdout
    assert "Sent back to the drafter with the check's findings." in ran.stdout
    assert "Accepted after 2 rounds (limit 3). 3 requests to the model" in ran.stdout


def test_the_demo_stopped_by_its_round_limit_goes_to_a_person_and_exits_1():
    ran = patterns_cli("revise", "--max-rounds", "1")
    assert ran.returncode == 1
    assert "Stopped after 1 round (limit 1): the draft still fails the check." in ran.stdout
    assert ran.stdout.rstrip().endswith(
        "A person reads this draft, and its problems, before anything is sent."
    )
