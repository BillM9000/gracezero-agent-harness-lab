"""Authorization inside the tools (chapter 11).

The triage assistant acts for one member of staff, and every tool checks what that person may see,
in code, on every call. A support agent sees the tickets assigned to them and the unassigned queue;
a lead sees everything. These tests play the model with direct calls, asking for exactly what the
person shouldn't get, which is what a model does when a prompt fails to stop it.
"""

from __future__ import annotations

import pytest

from helpdesk.assistant.narrow import narrow_tools
from helpdesk.assistant.tools import triage_tools
from helpdesk.model.types import ToolCall
from helpdesk.services import access
from helpdesk.services.access import Person
from helpdesk.services.errors import Invalid


def run(conn, person, name, **arguments):
    who = person if isinstance(person, Person) else access.find_person(conn, person)
    return triage_tools(conn, who).run(ToolCall("c1", name, arguments))


def test_a_ticket_assigned_to_someone_else_is_refused_inside_the_tool(conn):
    # Ticket 4 is assigned to Dana. Nothing in the prompt stops a model asking for it; the tool does.
    refused = run(conn, "sam", "get_ticket", ticket_id=4)
    assert refused.is_error
    assert refused.content.startswith("Sam Rivera can't see ticket 4:")
    assert "App crashes on login" not in refused.content

    shown = run(conn, "dana", "get_ticket", ticket_id=4)
    assert not shown.is_error
    assert shown.content.startswith("Ticket 4 [closed, normal priority]: App crashes on login")


def test_a_missing_ticket_and_one_you_cannot_see_get_the_same_answer(conn):
    # If the two answers differed, the error itself would tell Sam which ticket numbers exist.
    hidden = run(conn, "sam", "get_ticket", ticket_id=4).content
    missing = run(conn, "sam", "get_ticket", ticket_id=999).content
    assert hidden.replace("ticket 4", "ticket N") == missing.replace("ticket 999", "ticket N")


def test_lists_and_counts_hold_only_what_the_person_can_see(conn):
    sam = (
        run(conn, "sam", "find_tickets", status="any").content
        + run(conn, "sam", "find_tickets", status="any", page=2).content
    )
    assert "Tickets Sam Rivera can see (any status, any assignee): 9," in sam
    for hidden in ("#4 [", "#7 [", "#9 ["):
        assert hidden not in sam
    assert (
        "Tickets Dana Whitfield can see (any status, any assignee): 12,"
        in run(conn, "dana", "find_tickets", status="any").content
    )
    assert (
        "Tickets Priya Nair can see (any status, any assignee): 7,"
        in run(conn, "priya", "find_tickets", status="any").content
    )


def test_the_customers_other_tickets_are_trimmed_too(conn):
    # Ada's ticket 4 is Dana's, so it's missing from what Sam is told about Ada, and present for Dana.
    assert run(conn, "sam", "get_ticket", ticket_id=1).content.endswith(
        "Ada Park's other tickets that Sam Rivera can see: "
        "#11 [open] Notifications too frequent (2026-09-07)."
    )
    assert "#4 [closed] App crashes on login" in run(conn, "dana", "get_ticket", ticket_id=1).content


def test_the_model_cannot_choose_whose_permissions_to_use(conn):
    # No tool takes the person as an argument, and an argument a schema doesn't have is refused.
    result = run(conn, "sam", "get_ticket", ticket_id=4, staff_id=2)
    assert result.is_error
    assert "staff_id isn't one of its arguments (it takes ticket_id)" in result.content
    assert "App crashes on login" not in result.content


def test_a_role_the_rule_does_not_know_sees_nothing(conn):
    auditor = Person(9, "Vi Auditor", "auditor")
    assert not any(access.can_see(auditor, t) for t in conn.execute("SELECT * FROM tickets").fetchall())
    assert run(conn, auditor, "get_ticket", ticket_id=1).is_error
    assert (
        "No tickets that Vi Auditor can see match" in run(conn, auditor, "find_tickets", status="any").content
    )


def test_the_person_comes_from_whoever_starts_the_assistant(conn):
    assert access.find_person(conn, "Dana").label == "Dana Whitfield (lead)"
    assert access.find_person(conn, "3").label == "Priya Nair (support)"
    with pytest.raises(Invalid, match="No member of staff called 'bob'. Choose one of: sam"):
        access.find_person(conn, "bob")


def test_the_narrow_set_keeps_the_same_rule(conn):
    sam = access.find_person(conn, "sam")
    narrow = narrow_tools(conn, sam)
    assert narrow.run(ToolCall("c1", "get_ticket", {"ticket_id": 4})).is_error
    assert '"id": 4,' not in narrow.run(ToolCall("c2", "list_tickets", {})).content
    # With Dev's only unassigned ticket given to Priya, Sam can see none of Dev's tickets, or Dev.
    conn.execute("UPDATE tickets SET assignee_id = 3 WHERE id = 6")
    assert narrow.run(ToolCall("c3", "list_customer_tickets", {"customer_id": 4})).content == "[]"
    refused = narrow.run(ToolCall("c4", "get_customer", {"customer_id": 4}))
    assert refused.is_error
    assert refused.content == "There is no customer 4 with a ticket Sam Rivera can see."
