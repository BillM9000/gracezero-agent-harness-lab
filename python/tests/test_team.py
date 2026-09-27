"""Orchestrator and workers (chapter 14): one worker a customer, each in its own context, and the
result counted in code whatever the orchestrator's summary says."""

from __future__ import annotations

import subprocess
import sys

import pytest

from helpdesk import patterns
from helpdesk.assistant.team import DELEGATE, WORKER_TOOLS, orchestrator_tools, run_team
from helpdesk.assistant.tools import Tool, triage_tools
from helpdesk.model.mock import MockModel
from helpdesk.model.types import ModelResponse, ToolCall
from helpdesk.services import access, tickets

SUMMARY_SCRIPT_END = patterns.ORCHESTRATOR_SCRIPT[-1]


def team_for(conn, fail=None, workers=None):
    _, worker, _ = patterns.definitions()
    models, made = patterns.scripted_workers(fail)
    if workers is not None:
        made = {}

        def models(customer):
            made[customer] = MockModel(workers[customer])
            return made[customer]

    sam = access.find_person(conn, "sam")
    return patterns.build_team(conn, sam, worker, models), made


def run(conn, script=None, **kwargs):
    orchestrator, _, _ = patterns.definitions()
    team, made = team_for(conn, **kwargs)
    lead = MockModel(script or patterns.ORCHESTRATOR_SCRIPT)
    result = run_team(
        lead, team, system=orchestrator["system"], tools=orchestrator["tools"], task=patterns.BATCH_TASK
    )
    return result, lead, made


def delegating(*customers: str) -> list[ModelResponse]:
    """An orchestrator that lists the batch, delegates these customers, and claims it's all done."""
    turn = [
        ToolCall(f"d{i}", "delegate_customer", {"customer_name": c, "brief": patterns.BRIEF})
        for i, c in enumerate(customers)
    ]
    return [
        patterns.ORCHESTRATOR_SCRIPT[0],
        ModelResponse("tool_use", tool_calls=tuple(turn)),
        SUMMARY_SCRIPT_END,
    ]


def results_of(lead: MockModel) -> list[tuple[bool, str]]:
    """The delegate results the orchestrator read, in order: (is_error, content)."""
    return [(r.is_error, r.content) for r in lead.calls[-1].messages[-1].tool_results]


def test_the_batch_is_every_open_or_pending_ticket_the_person_can_see_by_customer(conn):
    team, _ = team_for(conn)
    assert team.batch() == patterns.CUSTOMERS


def test_every_customer_gets_one_worker_and_the_batch_is_complete(conn):
    result, _, made = run(conn)
    assert list(made) == list(patterns.CUSTOMERS)
    assert result.accounting.complete
    # Each draft starts with its ticket's number and subject, a sentence with nothing to cite.
    assert result.accounting.lines() == [
        "5 of 5 customers, 8 of 8 tickets, have drafts whose citations hold.",
        "In those drafts, 8 sentences cite nothing: Ada Park 2, Ben Oka"
        "for 2, Dev Mistry 1, Chloe Varga 2, Elif Kaya 1.",
    ]


def test_each_worker_starts_with_only_its_brief_and_only_reading_tools(conn):
    _, _, made = run(conn)
    for customer, model in made.items():
        first = model.calls[0]
        assert [m.role for m in first.messages] == ["user"]
        assert first.messages[0].content.startswith(patterns.BRIEF)
        assert f"all from {customer}." in first.messages[0].content
        assert patterns.BATCH_TASK not in first.messages[0].content
        assert [t.name for t in first.tools] == list(WORKER_TOOLS) == ["get_ticket", "search_kb"]


def test_the_orchestrator_gets_a_short_report_not_the_workers_drafts(conn):
    _, lead, _ = run(conn)
    for is_error, content in results_of(lead):
        assert not is_error
        assert "Reset emails" not in content and "[1#2]" not in content
        assert len(content) < 200


def test_a_customer_delegated_twice_is_refused_and_keeps_one_worker(conn):
    result, lead, made = run(conn, delegating("Ada Park", "Ada Park"))
    assert list(made) == ["Ada Park"]
    second = results_of(lead)[1]
    assert second[0] is True
    assert second[1].startswith("Ada Park was already delegated. One worker handles every ticket")


def test_an_unknown_customer_is_refused_with_how_to_name_one(conn):
    _, lead, made = run(conn, delegating("Zed Quinn"))
    assert made == {}
    is_error, content = results_of(lead)[0]
    assert is_error
    assert "from a customer called 'Zed Quinn'. Use the name exactly as find_tickets shows it." in content


def test_a_worker_that_stops_without_drafts_is_counted_as_failed_whatever_the_summary_says(conn):
    result, lead, _ = run(conn, fail="ben")
    assert result.orchestrator.answer.startswith("Drafts are ready for all 8")
    assert not result.accounting.complete
    assert list(result.accounting.failed) == ["Ben Okafor"]
    assert "cut off at max_tokens" in result.accounting.failed["Ben Okafor"]
    assert (
        result.accounting.lines()[0] == "4 of 5 customers, 6 of 8 tickets, have drafts whose citations hold."
    )
    is_error, content = results_of(lead)[1]
    assert is_error and content.startswith("The worker for Ben Okafor stopped without drafts:")
    assert content.endswith(
        "Tickets #12, #2 have no draft. Tell the person so, and don't count them as done."
    )


def test_the_count_is_made_even_when_the_orchestrator_stops_part_way(conn):
    # It delegates Ada, then keeps listing tickets until its turn limit stops it.
    listing = patterns.calls(("find_tickets", {}), turn="again")
    script = [*delegating("Ada Park")[:2], *[listing] * 6]
    result, _, _ = run(conn, script)
    assert result.orchestrator is None
    assert result.stopped.startswith("No answer after 6 turns")
    assert result.accounting.drafted == ("Ada Park",)
    assert result.accounting.missing == ("Ben Okafor", "Dev Mistry", "Chloe Varga", "Elif Kaya")


def test_a_customer_never_delegated_is_missing(conn):
    result, _, _ = run(conn, delegating("Ada Park", "Ben Okafor", "Dev Mistry", "Chloe Varga"))
    assert result.accounting.missing == ("Elif Kaya",)
    assert not result.accounting.complete
    assert result.accounting.lines()[-1] == "Never delegated: Elif Kaya (#10)."


def test_a_worker_whose_citations_fail_is_not_counted_as_drafted(conn):
    changed = patterns.drafts([10]).replace("Every charge has an invoice", "Every charge has two invoices")
    workers = {
        "Elif Kaya": [
            patterns.calls(*patterns.read_tickets([10]), turn="w1"),
            ModelResponse("end_turn", text=changed),
        ]
    }
    result, lead, _ = run(conn, delegating("Elif Kaya"), workers=workers)
    assert "Elif Kaya" in result.accounting.failed
    assert result.accounting.failed["Elif Kaya"].startswith("1 citation problem(s)")
    is_error, content = results_of(lead)[0]
    assert not is_error and "not usable yet: 1 citation problem(s)" in content


def test_a_worker_that_skips_a_ticket_is_not_counted(conn):
    # Ada has #1 and #11; this worker reads only #1, then writes both drafts anyway.
    reads = [
        ("get_ticket", {"ticket_id": 1}),
        ("search_kb", {"query": patterns.TICKETS[1][0]}),
        ("search_kb", {"query": patterns.TICKETS[11][0]}),
    ]
    workers = {
        "Ada Park": [
            patterns.calls(*reads, turn="w1"),
            ModelResponse("end_turn", text=patterns.drafts([1, 11])),
        ]
    }
    result, _, _ = run(conn, delegating("Ada Park"), workers=workers)
    assert result.accounting.failed["Ada Park"].startswith("its worker never read #11")


def test_the_orchestrator_has_find_tickets_and_delegate_and_a_tool_name_is_never_used_twice(conn):
    team, _ = team_for(conn)
    orchestrator, _, _ = patterns.definitions()
    assert [s.name for s in orchestrator_tools(team, orchestrator["tools"]).specs] == [
        "find_tickets",
        "delegate_customer",
    ]
    toolbox = triage_tools(conn, access.find_person(conn, "sam"))
    with pytest.raises(KeyError, match="already has a tool named get_ticket"):
        toolbox.plus(Tool(toolbox.specs[0], lambda **_: ""))
    assert DELEGATE.name not in [s.name for s in toolbox.specs]


def test_the_orchestrator_gets_the_tools_its_definition_names_and_no_other(conn):
    # agents/orchestrator.toml's tools used to be checked against the policy and nothing else: the
    # orchestrator got find_tickets and delegate_customer whatever the definition said.
    team, _ = team_for(conn)
    names = ["find_tickets", "get_ticket", "delegate_customer"]
    assert [s.name for s in orchestrator_tools(team, names).specs] == names
    for unknown in ("close_ticket", "send_email"):
        with pytest.raises(KeyError, match=f"No tool named {unknown}"):
            orchestrator_tools(team, ["find_tickets", unknown])
    lead = MockModel(patterns.ORCHESTRATOR_SCRIPT)
    result = run_team(lead, team, system="s", tools=["find_tickets"], task=patterns.BATCH_TASK)
    assert [spec.name for spec in lead.calls[0].tools] == ["find_tickets"]
    assert result.workers == ()


def test_a_team_counts_only_what_the_service_says_the_person_can_see(conn):
    # Dana, the lead, sees two more tickets: #9 (Dev Mistry) and #7 (Elif Kaya). Sam's scripts don't
    # read them, so the count says so rather than calling those customers done.
    _, worker, _ = patterns.definitions()
    models, _ = patterns.scripted_workers()
    dana = access.find_person(conn, "dana")
    team = patterns.build_team(conn, dana, worker, models)
    orchestrator, _, _ = patterns.definitions()
    result = run_team(
        MockModel(patterns.ORCHESTRATOR_SCRIPT),
        team,
        system=orchestrator["system"],
        tools=orchestrator["tools"],
        task=patterns.BATCH_TASK,
    )
    assert sorted(result.accounting.failed) == ["Dev Mistry", "Elif Kaya"]
    assert result.accounting.failed["Dev Mistry"].startswith("its worker never read #9")


# A review (2026-09-26) found three ways the count said done when it wasn't: an empty answer, an
# answer with no citation, and two customers with one name merged into one worker's batch.


def test_a_worker_that_answers_with_nothing_is_not_counted(conn):
    workers = {
        "Elif Kaya": [
            patterns.calls(*patterns.read_tickets([10]), turn="w1"),
            ModelResponse("end_turn", text=""),
        ]
    }
    result, lead, _ = run(conn, delegating("Elif Kaya"), workers=workers)
    assert result.accounting.failed == {"Elif Kaya": "its worker's answer was empty, so there are no drafts."}
    assert result.accounting.drafted == ()
    assert (
        result.accounting.lines()[0] == "0 of 5 customers, 0 of 8 tickets, have drafts whose citations hold."
    )
    is_error, content = results_of(lead)[0]
    assert not is_error and "not usable yet: its worker's answer was empty" in content


def test_a_worker_whose_answer_cites_nothing_is_not_counted(conn):
    uncited = "Hello Elif, thanks for writing. Your invoices are under Billing and can be downloaded."
    workers = {
        "Elif Kaya": [
            patterns.calls(*patterns.read_tickets([10]), turn="w1"),
            ModelResponse("end_turn", text=uncited),
        ]
    }
    result, _, _ = run(conn, delegating("Elif Kaya"), workers=workers)
    assert result.accounting.failed["Elif Kaya"] == (
        "its drafts cite no passage, so no check vouches for them; a person must read them."
    )
    assert result.accounting.drafted == ()


def test_a_greeting_without_a_citation_doesnt_stop_a_draft_counting_but_is_reported(conn):
    cited = "Hello Elif. " + patterns.drafts([10])
    workers = {
        "Elif Kaya": [
            patterns.calls(*patterns.read_tickets([10]), turn="w1"),
            ModelResponse("end_turn", text=cited),
        ]
    }
    result, lead, _ = run(conn, delegating("Elif Kaya"), workers=workers)
    assert result.accounting.drafted == ("Elif Kaya",)
    assert result.accounting.lines()[:2] == [
        "1 of 5 customers, 1 of 8 tickets, have drafts whose citations hold.",
        "In those drafts, 2 sentences cite nothing: Elif Kaya 2.",
    ]
    assert results_of(lead)[0][1].startswith(
        "Elif Kaya: drafts for #10, written in 2 turns; all 2 citations hold; 2 sentences cite nothing."
    )


def another_ada_park(conn) -> int:
    """A second customer called Ada Park, with one open ticket Sam can see."""
    conn.execute("INSERT INTO customers (id, name, email) VALUES (99, 'Ada Park', 'ada.park.2@example.com')")
    return tickets.create_ticket(conn, 99, "Two-factor codes", "My codes never arrive.")["id"]


def test_two_customers_with_one_name_are_two_customers(conn):
    second = another_ada_park(conn)
    team, _ = team_for(conn)
    batch = team.batch()
    assert batch["Ada Park (customer 1)"] == (1, 11)
    assert batch["Ada Park (customer 99)"] == (second,)
    assert "Ada Park" not in batch and len(batch) == 6


def test_a_shared_name_delegates_one_customer_at_a_time_and_the_count_names_each(conn):
    second = another_ada_park(conn)
    first = "Ada Park (customer 1)"
    workers = {first: patterns.worker_script("Ada Park")}
    result, lead, made = run(conn, delegating("Ada Park"), workers=workers)
    assert list(made) == [first]
    assert "all from Ada Park." in made[first].calls[0].messages[0].content
    is_error, content = results_of(lead)[0]
    assert not is_error
    assert content.endswith(
        f"Another customer is also called Ada Park, with #{second}: delegate Ada Park again for them."
    )
    assert result.accounting.drafted == (first,)
    assert "Ada Park (customer 99)" in result.accounting.missing
    assert f"Never delegated: Ada Park (customer 99) (#{second})." in result.accounting.lines()


def test_a_shared_name_delegated_again_goes_to_the_other_customer(conn):
    second = another_ada_park(conn)
    first, other = "Ada Park (customer 1)", "Ada Park (customer 99)"
    workers = {
        first: patterns.worker_script("Ada Park"),
        other: [ModelResponse("end_turn", text="")],
    }
    _, lead, made = run(conn, delegating("Ada Park", "Ada Park", "Ada Park"), workers=workers)
    assert list(made) == [first, other]
    assert f"The tickets: #{second}, all from Ada Park." in made[other].calls[0].messages[0].content
    third = results_of(lead)[2]
    assert third[0] is True and third[1].startswith("Ada Park was already delegated.")


def patterns_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "helpdesk.patterns", *args], capture_output=True, text=True)


def test_the_batch_demo_ends_with_the_count():
    ran = patterns_cli("batch")
    assert ran.returncode == 0, ran.stderr
    assert "Counted in code, not taken from the summary:" in ran.stdout
    assert (
        "  5 of 5 customers, 8 of 8 tickets, have drafts whose citations hold.\n  In those drafts, 8"
        in ran.stdout
    )
    assert ran.stdout.rstrip().endswith("Chloe Varga 2, Elif Kaya 1.")


def test_the_batch_with_a_failed_worker_stops_even_though_the_summary_claims_everything():
    ran = patterns_cli("batch", "--fail", "ben")
    assert ran.returncode == 1
    assert "Drafts are ready for all 8 open and pending tickets" in ran.stdout
    assert "  4 of 5 customers, 6 of 8 tickets, have drafts whose citations hold." in ran.stdout
    assert "  No usable drafts for Ben Okafor (#12, #2): The answer was cut off at max_tokens." in ran.stdout
    assert ran.stdout.rstrip().endswith(
        "Stopped: the batch isn't complete, whatever the summary says. Read what's missing above."
    )
