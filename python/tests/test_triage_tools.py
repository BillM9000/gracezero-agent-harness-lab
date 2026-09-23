from __future__ import annotations

from helpdesk.assistant.tools import triage_tools
from helpdesk.model.types import ToolCall


def call(conn, name, **arguments):
    return triage_tools(conn).run(ToolCall("c1", name, arguments))


def test_get_ticket_reads_the_ticket(conn):
    result = call(conn, "get_ticket", ticket_id=1)
    assert not result.is_error
    assert result.content.splitlines()[0] == "Ticket 1 [open, high priority]: Cannot reset my password"


def test_a_missing_ticket_is_an_error_the_model_can_read(conn):
    result = call(conn, "get_ticket", ticket_id=999)
    assert result.is_error
    assert result.content == "ticket 999 does not exist"


def test_search_kb_finds_an_article(conn):
    result = call(conn, "search_kb", query="password")
    assert not result.is_error
    assert result.content.startswith("Article 1, Resetting your password:")


def test_search_kb_says_what_to_try_when_nothing_matches(conn):
    result = call(conn, "search_kb", query="password reset email")
    assert not result.is_error
    assert "Try one shorter keyword" in result.content


def test_an_unknown_tool_names_the_tools_that_exist(conn):
    result = call(conn, "close_ticket", ticket_id=1)
    assert result.is_error
    assert result.content == "There is no tool named 'close_ticket'. Available tools: get_ticket, search_kb."


def test_arguments_are_checked_against_the_schema_before_the_tool_runs(conn):
    assert (
        call(conn, "get_ticket").content
        == "get_ticket needs ticket_id. Call it again with every required argument."
    )
    assert (
        call(conn, "get_ticket", ticket_id="1").content
        == "get_ticket: ticket_id must be of type integer; got '1'."
    )
    assert call(conn, "get_ticket", ticket_id=True).is_error
    assert (
        call(conn, "search_kb", query="x", limit=3).content
        == "search_kb does not take limit. It takes: query."
    )
