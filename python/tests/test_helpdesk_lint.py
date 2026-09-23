"""The helpdesk's own lint rule (chapter 17) catches what it claims to, and its messages teach.

Each test lints a few lines of source, so each one plants exactly one thing. The last tests run the
rule over the real helpdesk, which has one exception, with its reason.
"""

from __future__ import annotations

from pathlib import Path

from helpdesk_lint.__main__ import main
from helpdesk_lint.model_text import check

PYTHON_ROOT = Path(__file__).resolve().parents[1]


def problems(source: str) -> list[str]:
    found, _ = check(source)
    return [f"{p.line}:{p.column}: {p.message}" for p in found]


def test_reading_the_text_after_complete_is_caught_and_the_message_says_what_to_do():
    found = problems(
        "def answer(model):\n"
        "    response = model.complete(system='s', messages=[])\n"
        "    return response.text\n"
    )
    assert len(found) == 1
    assert found[0].startswith("3:12: HDK101 Read the model's text with final_text(response), not response.")
    assert "a refusal or a cut-off answer is a normal response with text of its own" in found[0].lower()
    assert found[0].endswith("# HDK101: <why>")


def test_a_parameter_annotated_as_a_model_response_is_caught():
    found = problems("def show(reply: ModelResponse | None) -> str:\n    return reply.text\n")
    assert len(found) == 1
    assert "final_text(reply), not reply.text" in found[0]


def test_reading_the_text_straight_off_the_call_is_caught():
    assert len(problems("def answer(model):\n    return model.complete(system='s', messages=[]).text\n")) == 1


def test_final_text_and_other_objects_text_pass():
    # A text search for ".text" would flag block.text and page.text; the visitor knows which names
    # hold a model response.
    assert (
        problems(
            "def answer(model, block, page):\n"
            "    response = model.complete(system='s', messages=[])\n"
            "    return final_text(response) + block.text + page.text\n"
        )
        == []
    )


def test_a_name_in_another_function_is_not_a_model_response():
    assert (
        problems(
            "def first(model):\n"
            "    response = model.complete(system='s', messages=[])\n"
            "    return final_text(response)\n"
            "def second(response):\n"
            "    return response.text\n"
        )
        == []
    )


def test_an_exception_with_a_reason_is_accepted_on_the_line_or_just_above_it():
    head = "def f(r: ModelResponse):\n"
    same_line = head + "    log(r.text)  # HDK101: logged for debugging, never shown\n"
    line_above = head + "    # HDK101: logged for debugging, never shown\n    log(r.text)\n"
    for source in (same_line, line_above):
        found, used = check(source)
        assert found == [], source
        assert [e.reason for e in used] == ["logged for debugging, never shown"]


def test_an_exception_without_a_reason_fails():
    found = problems("def f(r: ModelResponse):\n    log(r.text)  # HDK101\n")
    assert len(found) == 1
    assert found[0].startswith("2:1: HDK102 This HDK101 exception gives no reason.")


def test_an_exception_where_nothing_reads_the_text_fails():
    # The comment covers the line below it, which doesn't read r.text, so the exception is stale.
    found = problems(
        "def f(r: ModelResponse):\n    # HDK101: kept for the transcript\n    return final_text(r)\n"
    )
    assert len(found) == 1
    assert found[0].startswith("2:1: HDK103")


def test_the_helpdesk_passes_with_one_exception_that_says_why(capsys, monkeypatch):
    monkeypatch.chdir(PYTHON_ROOT)
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "0 problem(s), 1 exception(s)." in output
    assert "exception at src/helpdesk/assistant/agent.py:" in output
    assert "the answer goes through final_text below" in output


def test_the_model_package_is_exempt_and_a_run_that_checks_nothing_fails(capsys):
    # helpdesk.model is where final_text reads the text; pointed only at it, the rule has nothing
    # to check, and says so instead of passing.
    assert main([str(PYTHON_ROOT / "src" / "helpdesk" / "model")]) == 2
    assert "nothing was checked" in capsys.readouterr().err
