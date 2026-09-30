"""The triage assistant's tools: what each returns, and how a bad call is answered."""

from __future__ import annotations

from agent_policy import AGENTS, POLICY, load
from helpdesk.assistant.proposing import assistant_tools
from helpdesk.assistant.tools import triage_tools
from helpdesk.model.types import ToolCall
from helpdesk.services import access

POLICY_WRITES = load(POLICY)["writes"]


def call(conn, name, *, person="sam", **arguments):
    return triage_tools(conn, access.find_person(conn, person)).run(ToolCall("c1", name, arguments))


def test_the_assistants_tools_only_read(conn):
    # The README says the assistant's reading tools only read. A counter could check how many there
    # are; only a test can check "read-only". A tool that changes anything needs a person's approval
    # first (chapter 19), so adding one should fail here and be a decision, not a quiet change. When
    # chapter 19 gave the assistant draft_reply and close_ticket, the decision was recorded three
    # times: each tool is marked as writing, agents/policy.toml names it with the least approval it
    # needs, and the definition says whose approval it takes. Every tool not marked must still read.
    def snapshot():
        return [
            [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in ("tickets", "replies", "kb_articles", "customers", "staff", "proposals")
        ]

    before = snapshot()
    for person in ("sam", "dana"):
        toolbox = assistant_tools(conn, access.find_person(conn, person), load(AGENTS / "triage.toml"))
        readers = {spec.name for spec in toolbox.specs if spec.name not in toolbox.writers}
        assert readers == {"get_ticket", "find_tickets", "search_kb"}
        assert set(toolbox.writers) == set(POLICY_WRITES)
        toolbox.run(ToolCall("c1", "get_ticket", {"ticket_id": 1}))
        toolbox.run(ToolCall("c2", "find_tickets", {"status": "any"}))
        toolbox.run(ToolCall("c3", "search_kb", {"query": "password"}))
    assert snapshot() == before


def test_get_ticket_reads_the_ticket_in_context(conn):
    result = call(conn, "get_ticket", ticket_id=5)
    assert not result.is_error
    assert result.content.splitlines() == [
        'Ticket 5 [closed, low priority]: "Can I downgrade mid-month?"',
        'From "Ben Okafor", opened 2026-08-12. Assigned to Sam Rivera.',
        'The customer wrote: "If I move from Pro to Free today, do I lose Pro straight away?"',
        "Replies, oldest first:",
        "  Sam Rivera (staff), 2026-08-12: No: plan changes take effect at the next billing date, and "
        "until then you keep Pro.",
        '  "Ben Okafor" (customer), 2026-08-12: "Thanks, that\'s clear."',
        'The customer\'s other tickets that Sam Rivera can see: #2 [open] "Invoice shows the wrong plan" '
        '(2026-09-02); #12 [open] "API token stopped working" (2026-09-08).',
    ]


def test_a_missing_ticket_is_an_error_the_model_can_read(conn):
    result = call(conn, "get_ticket", ticket_id=999, person="dana")
    assert result.is_error
    assert result.content == "Ticket 999 doesn't exist. Use find_tickets to list the tickets there are."


def test_a_ticket_number_too_big_for_sqlite_is_a_ticket_that_doesnt_exist(conn):
    # Chapter 3: the schema allows any integer from 1, and SQLite stores at most 8 bytes, so a 20-digit
    # number used to stop the run with an OverflowError. It's a missing ticket, and says so.
    for ticket_id in (2**63, 10**19, 10**40):
        result = call(conn, "get_ticket", ticket_id=ticket_id, person="dana")
        assert result.is_error
        assert result.content == (
            f"Ticket {ticket_id} doesn't exist. Use find_tickets to list the tickets there are."
        )
    assert not call(conn, "get_ticket", ticket_id=1, person="dana").is_error


def test_find_tickets_lists_in_the_order_to_handle_them(conn):
    lines = call(conn, "find_tickets").content.splitlines()
    assert lines[0] == (
        "Tickets Sam Rivera can see (open or pending, any assignee): 8, highest priority first. Page 1 of 2."
    )
    assert [line.split()[0] for line in lines[1:6]] == ["#1", "#12", "#2", "#6", "#8"]
    assert lines[1] == (
        '#1 [open, high] "Cannot reset my password" ("Ada Park"; unassigned; opened 2026-09-01)'
    )


def test_search_kb_returns_passages_each_with_an_id_to_cite(conn):
    result = call(conn, "search_kb", query="password")
    assert not result.is_error
    assert result.content.splitlines()[0].startswith(
        "[1#1] Resetting your password > Send yourself a reset link:"
    )
    assert len(result.content.splitlines()) == 3


def test_search_kb_finds_a_question_the_keyword_filter_missed(conn):
    # Until chapter 9, search_kb matched the whole query as one piece of text, so this found nothing.
    result = call(conn, "search_kb", query="password reset email")
    assert result.content.startswith("[1#")


def test_search_kb_says_what_to_do_when_nothing_matches(conn):
    result = call(conn, "search_kb", query="What is the capital of France?")
    assert not result.is_error
    assert "Say so in the reply; don't guess." in result.content


def test_an_unknown_tool_names_the_tools_that_exist(conn):
    result = call(conn, "close_ticket", ticket_id=1)
    assert result.is_error
    assert result.content == (
        "There is no tool named 'close_ticket'. Available tools: find_tickets, get_ticket, search_kb."
    )


def test_arguments_are_checked_against_the_schema_before_the_tool_runs(conn):
    assert call(conn, "get_ticket").content == (
        "get_ticket wasn't run: ticket_id is missing. Call it again with that fixed."
    )
    assert call(conn, "get_ticket", ticket_id="1").content == (
        'get_ticket wasn\'t run: ticket_id must be a whole number, not "1". Call it again with that fixed.'
    )
    assert call(conn, "get_ticket", ticket_id=True).is_error
    assert call(conn, "search_kb", query="x", limit=3).content == (
        "search_kb wasn't run: limit isn't one of its arguments (it takes query). "
        "Call it again with that fixed."
    )
