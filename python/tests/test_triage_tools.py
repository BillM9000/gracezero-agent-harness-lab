from __future__ import annotations

from helpdesk.assistant.tools import triage_tools
from helpdesk.model.types import ToolCall


def call(conn, name, **arguments):
    return triage_tools(conn).run(ToolCall("c1", name, arguments))


def test_the_assistants_tools_only_read(conn):
    # The README says the assistant has two read-only tools. A counter could check the "two";
    # only a test can check "read-only". A tool that changes anything needs a person's approval
    # first (chapter 19), so adding one should fail here and be a decision, not a quiet change.
    toolbox = triage_tools(conn)
    assert {spec.name for spec in toolbox.specs} == {"get_ticket", "search_kb"}

    def snapshot():
        return [
            [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in ("tickets", "replies", "kb_articles")
        ]

    before = snapshot()
    toolbox.run(ToolCall("c1", "get_ticket", {"ticket_id": 1}))
    toolbox.run(ToolCall("c2", "search_kb", {"query": "password"}))
    assert snapshot() == before


def test_get_ticket_reads_the_ticket(conn):
    result = call(conn, "get_ticket", ticket_id=1)
    assert not result.is_error
    assert result.content.splitlines()[0] == "Ticket 1 [open, high priority]: Cannot reset my password"


def test_a_missing_ticket_is_an_error_the_model_can_read(conn):
    result = call(conn, "get_ticket", ticket_id=999)
    assert result.is_error
    assert result.content == "ticket 999 does not exist"


def test_a_ticket_number_too_big_for_sqlite_is_a_ticket_that_doesnt_exist(conn):
    # Chapter 3: the schema allows any integer from 1, and SQLite stores at most 8 bytes, so a 20-digit
    # number used to stop the run with an OverflowError. It's a missing ticket, and says so.
    for ticket_id in (2**63, 10**19, 10**40):
        result = call(conn, "get_ticket", ticket_id=ticket_id)
        assert result.is_error
        assert result.content == f"ticket {ticket_id} does not exist"
    assert not call(conn, "get_ticket", ticket_id=1).is_error


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
