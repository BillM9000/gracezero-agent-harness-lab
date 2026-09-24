"""Results sized for a context window, and failures a model can act on (chapter 11)."""

from __future__ import annotations

import logging

from helpdesk.assistant.tools import MAX_RESULT_CHARS, Tool, Toolbox, triage_tools
from helpdesk.model.types import ToolCall, ToolSpec
from helpdesk.services import access

OPEN = {"type": "object", "properties": {}, "additionalProperties": False}


def call(conn, name, person="sam", **arguments):
    return triage_tools(conn, access.find_person(conn, person)).run(ToolCall("c1", name, arguments))


def test_a_page_says_how_many_match_and_how_to_get_the_next(conn):
    lines = call(conn, "find_tickets").content.splitlines()
    assert lines[0].endswith(": 8, highest priority first. Page 1 of 2.")
    assert len(lines) == 7
    assert lines[-1] == "More on page 2: call find_tickets again with the same filters and page 2."


def test_the_last_page_says_it_is_the_last(conn):
    lines = call(conn, "find_tickets", page=2).content.splitlines()
    assert [line.split()[0] for line in lines[1:-1]] == ["#3", "#10", "#11"]
    assert lines[-1] == "That's all of them."


def test_a_page_past_the_end_names_the_last_page(conn):
    result = call(conn, "find_tickets", page=3)
    assert result.is_error
    assert result.content == "page 3 is past the end: 8 tickets match, 5 to a page, so the last page is 2."


def test_no_match_says_how_to_widen_the_search(conn):
    result = call(conn, "find_tickets", status="closed", assignee="unassigned")
    assert not result.is_error
    assert result.content == (
        "No tickets that Sam Rivera can see match (closed, unassigned). To widen the search, leave status "
        'out or use "any", and use assignee "anyone".'
    )


def test_a_result_over_the_limit_is_cut_at_a_line_and_says_how_to_ask_for_less(conn):
    toolbox = triage_tools(conn, access.find_person(conn, "sam")).limited(300)
    content = toolbox.run(ToolCall("c1", "find_tickets", {})).content
    lines = content.splitlines()
    assert lines[-1] == (
        "[Cut: this result was 601 characters, and only the first 269 are shown. Use the status or assignee "
        "filters to ask for fewer tickets.]"
    )
    assert lines[-2].startswith("#12 [open, high]")  # whole lines only
    assert len("\n".join(lines[:-1])) == 269


def test_a_result_under_the_limit_is_untouched(conn):
    full = call(conn, "find_tickets").content
    assert len(full) < MAX_RESULT_CHARS
    assert "[Cut:" not in full


def test_an_unexpected_failure_says_not_to_retry_and_logs_the_traceback(caplog):
    def broken() -> str:
        raise KeyError("assignee_name")

    box = Toolbox([Tool(ToolSpec("broken", "Fails.", OPEN, strict=True), broken)])
    with caplog.at_level(logging.ERROR):
        result = box.run(ToolCall("c1", "broken", {}))
    assert result.is_error
    assert result.content == (
        "broken failed with an unexpected KeyError. That is a fault in the tool, not in your arguments, "
        "so calling it again the same way won't help. Tell the person this tool failed, and carry on "
        "without it if you can."
    )
    assert "assignee_name" not in result.content  # the internals stay with the person debugging
    assert "tool broken failed" in caplog.text
    assert "KeyError: 'assignee_name'" in caplog.text
