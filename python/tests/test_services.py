from __future__ import annotations

import pytest

from helpdesk.services import kb, tickets
from helpdesk.services.errors import Conflict, Invalid, NotFound


def clock() -> str:
    return "2026-09-22T12:00:00+00:00"


def test_new_ticket_is_open_with_no_replies(conn):
    ticket = tickets.create_ticket(conn, 2, "Refund question", "Was I charged twice?", clock=clock)
    assert ticket["status"] == "open"
    assert ticket["priority"] == "normal"
    assert ticket["replies"] == []
    assert ticket["created_at"] == clock()


def test_ticket_for_unknown_customer_is_invalid(conn):
    with pytest.raises(Invalid, match="customer 99 does not exist"):
        tickets.create_ticket(conn, 99, "Hello", "Anyone there?")


def test_blank_subject_is_invalid(conn):
    with pytest.raises(Invalid, match="subject must not be empty"):
        tickets.create_ticket(conn, 1, "   ", "Body")


def test_list_filters_by_status(conn):
    assert [t["id"] for t in tickets.list_tickets(conn, "open")] == [1, 2, 6, 7, 8, 10, 11, 12]
    assert [t["id"] for t in tickets.list_tickets(conn)] == list(range(1, 13))


def test_unknown_status_is_invalid(conn):
    with pytest.raises(Invalid, match="status must be one of"):
        tickets.list_tickets(conn, "archived")


def test_missing_ticket_is_not_found(conn):
    with pytest.raises(NotFound, match="ticket 999 does not exist"):
        tickets.get_ticket(conn, 999)


def test_replies_are_kept_in_order(conn):
    tickets.add_reply(conn, 1, "staff", "Checking now.", author_id=1, clock=clock)
    ticket = tickets.add_reply(conn, 1, "customer", "Thanks!", clock=clock)
    assert [r["body"] for r in ticket["replies"]] == ["Checking now.", "Thanks!"]


def test_reply_to_closed_ticket_is_a_conflict(conn):
    with pytest.raises(Conflict, match="reopen it before replying"):
        tickets.add_reply(conn, 4, "customer", "Still broken")


def test_only_staff_can_close_a_ticket(conn):
    with pytest.raises(Invalid, match="only staff can close tickets"):
        tickets.close_ticket(conn, 1, staff_id=99)


def test_closing_records_status_and_time(conn):
    ticket = tickets.close_ticket(conn, 1, staff_id=1, clock=clock)
    assert ticket["status"] == "closed"
    assert ticket["closed_at"] == clock()


def test_closing_twice_is_a_conflict(conn):
    with pytest.raises(Conflict, match="already closed"):
        tickets.close_ticket(conn, 4, staff_id=1)


def test_kb_search_is_an_exact_filter_on_title_body_and_tags(conn):
    assert [a["id"] for a in kb.search(conn, "password")] == [1, 5, 11]
    assert [a["id"] for a in kb.search(conn, "csv")] == [3, 10]
    assert [a["id"] for a in kb.search(conn, "E-4012")] == [5]


def test_kb_search_rejects_empty_query_and_bad_limit(conn):
    with pytest.raises(Invalid, match="query must not be empty"):
        kb.search(conn, "  ")
    with pytest.raises(Invalid, match="limit must be between"):
        kb.search(conn, "password", limit=0)
