"""The approval queue (chapter 19): an agent proposes, a person approves or rejects, and every step is
recorded. The tools that write never change a ticket; only an approval does, and only by someone the
change needs."""

from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from agent_policy import AGENTS, load
from helpdesk.assistant.proposing import assistant_tools
from helpdesk.assistant.tools import triage_tools
from helpdesk.data import repository
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed
from helpdesk.model.types import ToolCall
from helpdesk.services import access, decisions, tickets
from helpdesk.services.errors import Conflict, Forbidden, Invalid, NotFound

TRIAGE = load(AGENTS / "triage.toml")
REASON = "Don't promise a refund: they aren't automatic. Tell Ben how to request one."


def clock() -> str:
    return "2026-09-24T09:00:00+00:00"


def person(conn, who):
    return access.find_person(conn, who)


def tools(conn, who="sam", definition=TRIAGE):
    return assistant_tools(conn, person(conn, who), definition)


def call(conn, name, who="sam", definition=TRIAGE, **arguments):
    return tools(conn, who, definition).run(ToolCall("c1", name, arguments))


def rows(conn, *tables):
    return {table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")] for table in tables}


def events(conn):
    return [(r["event"], r["proposal_id"], r["ticket_id"], r["staff_id"]) for r in repository.list_log(conn)]


def test_a_draft_reply_changes_nothing_until_a_person_approves_it(conn):
    result = call(conn, "draft_reply", ticket_id=2, reply_text="Hello Ben.")
    assert not result.is_error
    assert result.content.startswith(
        "Filed proposal #1: send this reply on ticket 2. Nothing has changed yet."
    )
    assert tickets.get_ticket(conn, 2)["replies"] == []
    assert (
        decisions.approve(conn, person(conn, "sam"), 1, clock) == "the reply is on ticket 2, from Sam Rivera"
    )
    [reply] = tickets.get_ticket(conn, 2)["replies"]
    assert (reply["author_kind"], reply["author_id"], reply["body"]) == ("staff", 1, "Hello Ben.")


def test_the_tools_that_write_change_nothing_but_the_approval_queue(conn):
    record = ("tickets", "replies", "customers", "staff", "kb_articles")
    before = rows(conn, *record)
    assert not call(conn, "draft_reply", ticket_id=2, reply_text="Hello Ben.").is_error
    assert not call(conn, "close_ticket", ticket_id=3, reason="Answered by the article.").is_error
    assert rows(conn, *record) == before
    assert len(rows(conn, "proposals")["proposals"]) == 2
    assert [e[0] for e in events(conn)] == ["proposed", "proposed"]


def test_support_staff_see_the_unassigned_queue_but_change_only_their_own_tickets(conn):
    result = call(conn, "draft_reply", ticket_id=1, reply_text="Hello Ada.")
    assert result.is_error
    assert result.content == (
        "Sam Rivera can see ticket 1 but can't change it: support staff change only the tickets assigned "
        "to them. Nothing was filed. Ask a lead to assign it to Sam first."
    )
    # A ticket Sam can't see gets the same answer as one that doesn't exist, for writes as for reads.
    assert call(conn, "close_ticket", ticket_id=4, reason="x").content == access.cannot_see(
        person(conn, "sam"), 4
    )
    assert rows(conn, "proposals") == {"proposals": []}
    assert [e[0] for e in events(conn)] == ["refused", "refused"]
    # The lead may change any ticket.
    assert not call(conn, "draft_reply", "dana", ticket_id=1, reply_text="Hello Ada.").is_error


def test_closing_a_ticket_needs_a_lead_and_support_staff_are_refused(conn):
    filed = call(conn, "close_ticket", ticket_id=3, reason="Answered by the article.").content
    assert filed.endswith(
        "It needs a lead's approval, and Sam Rivera is support, so it waits for a lead. Tell Sam that a "
        "lead has to approve it."
    )
    sam, dana = person(conn, "sam"), person(conn, "dana")
    assert [p["id"] for p in decisions.queue(conn, sam).others] == [1]
    assert decisions.queue(conn, sam).theirs == []
    with pytest.raises(Forbidden, match="#1 needs the approval of a lead, and Sam Rivera is support"):
        decisions.approve(conn, sam, 1, clock)
    assert tickets.get_ticket(conn, 3)["status"] == "pending"
    assert [p["id"] for p in decisions.queue(conn, dana).theirs] == [1]
    assert decisions.approve(conn, dana, 1, clock) == "ticket 3 is closed"
    assert tickets.get_ticket(conn, 3)["status"] == "closed"
    assert [e[0] for e in events(conn)] == ["proposed", "refused", "approved"]


def test_a_rejection_needs_a_reason_and_the_assistant_reads_it_on_the_ticket(conn):
    call(conn, "draft_reply", ticket_id=2, reply_text="We'll refund you today.")
    sam = person(conn, "sam")
    with pytest.raises(Invalid, match="Give a reason"):
        decisions.reject(conn, sam, 1, "   ", clock)
    decisions.reject(conn, sam, 1, REASON, clock)
    ticket = call(conn, "get_ticket", ticket_id=2).content.splitlines()
    assert ticket[-2:] == [
        "Changes proposed on this ticket, oldest first:",
        f'  #1 reply: rejected by Sam Rivera, who said: "{REASON}"',
    ]
    # Once decided, the ticket takes a new draft.
    assert not call(conn, "draft_reply", ticket_id=2, reply_text="Refunds aren't automatic.").is_error


def test_one_reply_at_a_time_waits_on_a_ticket(conn):
    call(conn, "draft_reply", ticket_id=2, reply_text="First.")
    second = call(conn, "draft_reply", ticket_id=2, reply_text="Second.")
    assert second.is_error
    assert second.content.startswith("Proposal #1 to send a reply on ticket 2 is still waiting for approval")


def test_a_proposal_is_decided_once(conn):
    call(conn, "draft_reply", ticket_id=2, reply_text="Hello Ben.")
    sam = person(conn, "sam")
    decisions.approve(conn, sam, 1, clock)
    with pytest.raises(Conflict, match="#1 was already approved"):
        decisions.reject(conn, sam, 1, "Too late.", clock)
    assert len(tickets.get_ticket(conn, 2)["replies"]) == 1


def test_approving_checks_again_that_the_change_can_still_be_made(conn):
    call(conn, "draft_reply", ticket_id=2, reply_text="Hello Ben.")
    tickets.close_ticket(conn, 2, staff_id=1)  # closed by hand after the draft was filed
    with pytest.raises(Conflict, match="Ticket 2 was closed after #1 was filed"):
        decisions.approve(conn, person(conn, "sam"), 1, clock)
    assert tickets.get_ticket(conn, 2)["replies"] == []
    assert [e[0] for e in events(conn)] == ["proposed", "refused"]


def test_the_decision_the_change_and_its_record_commit_together(conn, monkeypatch):
    # The record is written last. If it can't be written, the reply isn't sent and the proposal is
    # still pending: there is no change without a record, and no record of a change that didn't happen.
    call(conn, "draft_reply", ticket_id=2, reply_text="Hello Ben.")
    record = repository.insert_log

    def broken(conn, at, event, *args, **kwargs):
        if event == "approved":
            raise RuntimeError("the disk is full")
        record(conn, at, event, *args, **kwargs)

    monkeypatch.setattr(repository, "insert_log", broken)
    with pytest.raises(RuntimeError):
        decisions.approve(conn, person(conn, "sam"), 1, clock)
    monkeypatch.undo()
    assert repository.get_proposal(conn, 1)["status"] == "pending"
    assert tickets.get_ticket(conn, 2)["replies"] == []
    assert [e[0] for e in events(conn)] == ["proposed"]


def test_a_decided_proposal_cannot_be_decided_again_even_by_two_at_once(conn):
    # The checks read the proposal, then the update writes it. Two people approving in the same
    # moment both pass the checks; the update itself only changes a proposal that is still pending.
    call(conn, "draft_reply", ticket_id=2, reply_text="Hello Ben.")
    assert repository.decide_proposal(conn, 1, "approved", 1, None, clock())
    assert not repository.decide_proposal(conn, 1, "rejected", 2, "No.", clock())


def test_a_reply_and_a_close_approved_at_once_on_one_ticket_cant_both_succeed(tmp_path, monkeypatch):
    # Two people at two terminals: two connections to one database file, each in its own thread.
    # Dana approves closing ticket 2 and is held just after her checks, before she writes; Sam then
    # approves a reply on the same ticket. Checks that only read would let Sam pass them too, and both
    # would succeed: a reply sent on a closed ticket. With the write lock held from the checks, Sam
    # waits for Dana, then is checked against her close and refused.
    path = tmp_path / "helpdesk-two-at-once.db"
    first = connect(path)
    init_schema(first)
    seed(first)
    second = connect(path)
    try:
        assert not call(first, "close_ticket", ticket_id=2, reason="Answered by the article.").is_error
        assert not call(first, "draft_reply", ticket_id=2, reply_text="Hello Ben.").is_error
        close_id, reply_id = 1, 2
        decide = repository.decide_proposal
        checked, go = threading.Event(), threading.Event()

        def held(conn, proposal_id, *args):
            if proposal_id == close_id:
                checked.set()
                go.wait(10)
            return decide(conn, proposal_id, *args)

        monkeypatch.setattr(repository, "decide_proposal", held)
        results: dict[str, object] = {}

        def approve(conn, who, proposal_id):
            try:
                results[who] = decisions.approve(conn, person(conn, who), proposal_id, clock)
            except Exception as error:  # the test reads what each approval ended with
                results[who] = error

        dana = threading.Thread(target=approve, args=(first, "dana", close_id))
        dana.start()
        assert checked.wait(10), "Dana's approval never reached its write"
        sam = threading.Thread(target=approve, args=(second, "sam", reply_id))
        sam.start()
        sam.join(0.5)  # unguarded, Sam's approval finishes here; guarded, it waits for Dana's lock
        go.set()
        dana.join(10)
        sam.join(10)
        monkeypatch.undo()

        assert results["dana"] == "ticket 2 is closed"
        assert isinstance(results["sam"], Conflict), results["sam"]
        assert str(results["sam"]) == (
            f"Ticket 2 was closed after #{reply_id} was filed, so the reply can't be sent. "
            "Nothing changed; reject it with that reason."
        )
        assert tickets.get_ticket(first, 2)["replies"] == []
        assert tickets.get_ticket(first, 2)["status"] == "closed"
        assert repository.get_proposal(first, reply_id)["status"] == "pending"
        assert [e[0] for e in events(first)] == ["proposed", "proposed", "approved", "refused"]
    finally:
        second.close()
        first.close()


def test_support_staff_cannot_approve_a_change_to_a_ticket_that_isnt_theirs(conn):
    # Dana's assistant proposes a reply on the unassigned ticket 1. Sam can see it, but may not
    # change ticket 1, so he may not approve a change to it either.
    call(conn, "draft_reply", "dana", ticket_id=1, reply_text="Hello Ada.")
    sam = person(conn, "sam")
    assert [p["id"] for p in decisions.queue(conn, sam).others] == [1]
    with pytest.raises(Forbidden, match="Sam Rivera is support, so Sam can't approve it"):
        decisions.approve(conn, sam, 1, clock)
    assert tickets.get_ticket(conn, 1)["replies"] == []


def test_only_someone_who_may_decide_sees_where_a_reply_goes(conn):
    # A team may ask for more than the policy's least: here every reply waits for a lead.
    strict = {**TRIAGE, "approval": {"draft_reply": "lead", "close_ticket": "lead"}}
    call(conn, "draft_reply", definition=strict, ticket_id=2, reply_text="Hello Ben.")
    assert decisions.recipient(conn, person(conn, "dana"), 1) == "Ben Okafor <ben.okafor@example.com>"
    with pytest.raises(Forbidden, match="Only someone who may decide #1 sees where it goes"):
        decisions.recipient(conn, person(conn, "sam"), 1)
    with pytest.raises(NotFound, match="no proposal #1 that Priya Nair can see"):
        decisions.recipient(conn, person(conn, "priya"), 1)


def test_a_role_the_rules_dont_know_can_change_and_approve_nothing():
    ticket = {"id": 2, "assignee_id": 9}
    auditor = access.Person(9, "Ann Auditor", "auditor")
    assert not access.can_change(auditor, ticket)
    assert not access.may_approve(auditor, "staff", ticket)
    lead = access.Person(2, "Dana Whitfield", "lead")
    assert not access.may_approve(lead, "owner", ticket)  # an approval nobody knows, nobody gives


def test_every_step_is_recorded_refusals_included(conn):
    call(conn, "draft_reply", ticket_id=2, reply_text="We'll refund you today.")
    call(conn, "close_ticket", ticket_id=3, reason="Answered by the article.")
    call(conn, "draft_reply", ticket_id=1, reply_text="Hello Ada.")
    sam, dana = person(conn, "sam"), person(conn, "dana")
    with pytest.raises(Forbidden):
        decisions.approve(conn, sam, 2, clock)
    with pytest.raises(NotFound):
        decisions.approve(conn, sam, 99, clock)
    decisions.reject(conn, sam, 1, REASON, clock)
    decisions.approve(conn, dana, 2, clock)
    assert events(conn) == [
        ("proposed", 1, 2, 1),
        ("proposed", 2, 3, 1),
        ("refused", None, 1, 1),
        ("refused", 2, 3, 1),
        ("refused", None, None, 1),
        ("rejected", 1, 2, 1),
        ("approved", 2, 3, 2),
    ]
    # The agent's steps say which agent took them; a person's decisions name only the person.
    assert [r["agent"] for r in repository.list_log(conn)] == ["triage"] * 3 + [None] * 4


def test_reading_tools_still_only_read_with_proposals_on_the_ticket(conn):
    call(conn, "draft_reply", ticket_id=2, reply_text="Hello Ben.")
    before = rows(conn, "tickets", "replies", "proposals", "approval_log")
    readers = triage_tools(conn, person(conn, "sam"))
    readers.run(ToolCall("c1", "get_ticket", {"ticket_id": 2}))
    assert rows(conn, "tickets", "replies", "proposals", "approval_log") == before


# The command lines, run the way a reader runs them.


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", *args], capture_output=True, text=True)


def test_the_whole_flow_from_the_command_line(tmp_path):
    db = str(tmp_path / "helpdesk.db")
    proposed = run("helpdesk.triage", "--demo", "propose", "--db", db)
    assert proposed.returncode == 0, proposed.stderr
    assert "result: Filed proposal #1: send this reply on ticket 2." in proposed.stdout
    assert "result: Filed proposal #2: close ticket 3." in proposed.stdout
    assert "error: Sam Rivera can see ticket 1 but can't change it" in proposed.stdout
    assert "Nothing was saved" not in proposed.stdout

    listed = run("helpdesk.approvals", "--db", db, "list", "--as", "sam").stdout.splitlines()
    assert listed == [
        "For Sam Rivera (support) to decide: 1",
        "  #1  reply on ticket 2 (Invoice shows the wrong plan), filed by triage for Sam Rivera",
        "Waiting for someone else: 1",
        "  #2  close ticket 3 (How do I export my data?), filed by triage for Sam Rivera, needs a lead",
    ]
    shown = run("helpdesk.approvals", "--db", db, "show", "1", "--as", "sam").stdout
    assert "To: Ben Okafor <ben.okafor@example.com>" in shown
    refused = run("helpdesk.approvals", "--db", db, "approve", "2", "--as", "sam")
    assert refused.returncode == 1
    assert refused.stderr.startswith("Refused: #2 needs the approval of a lead")

    rejected = run("helpdesk.approvals", "--db", db, "reject", "1", "--as", "sam", "--reason", REASON)
    assert rejected.stdout == "Rejected #1. The assistant reads why the next time it looks at ticket 2.\n"
    redrafted = run("helpdesk.triage", "--demo", "redraft", "--db", db)
    assert f'#1 reply: rejected by Sam Rivera, who said: "{REASON}"' in redrafted.stdout
    assert "result: Filed proposal #3: send this reply on ticket 2." in redrafted.stdout

    approved = run("helpdesk.approvals", "--db", db, "approve", "3", "--as", "sam")
    assert approved.stdout == "Approved #3: the reply is on ticket 2, from Sam Rivera.\n"
    logged = run("helpdesk.approvals", "--db", db, "log").stdout.splitlines()
    assert [line.split()[1] for line in logged] == [
        "event", "proposed", "proposed", "refused", "refused", "rejected", "proposed", "approved"
    ]  # fmt: skip


def test_a_run_in_memory_says_its_proposals_are_gone():
    ran = run("helpdesk.triage", "--demo", "propose")
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.rstrip().endswith(
        "Add --db .run/helpdesk.db to keep them for python -m helpdesk.approvals."
    )


def test_deciding_needs_to_know_who_is_deciding(tmp_path):
    ran = run("helpdesk.approvals", "--db", str(tmp_path / "h.db"), "approve", "1")
    assert ran.returncode == 2
    assert "the following arguments are required: --as" in ran.stderr
