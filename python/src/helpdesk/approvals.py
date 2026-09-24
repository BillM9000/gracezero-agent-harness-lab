"""Composition root for the approval queue (chapter 19): where a person decides what an agent proposed.

python -m helpdesk.approvals list --as sam              what Sam may decide, and what waits for others
python -m helpdesk.approvals show 1 --as sam            one proposal in full, and where a reply goes
python -m helpdesk.approvals approve 1 --as sam         approve it, and the change happens
python -m helpdesk.approvals reject 1 --as sam --reason "what to change"
python -m helpdesk.approvals log                        every step, refusals included

The triage assistant files proposals with draft_reply and close_ticket (python -m helpdesk.triage
--demo propose --db .run/helpdesk.db); nothing changes a ticket until someone approves here. It works
in the saved helpdesk, .run/helpdesk.db (HELPDESK_RUN_DIR moves .run; --db names another file),
created with the sample data the first time. --as names who is deciding: in a real app, the person
who is signed in. In the lab it names the person; it doesn't prove who. This is the only module that
may import helpdesk.services.decisions (a contract in pyproject.toml), so no tool reaches it.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Any

from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import is_seeded, seed
from helpdesk.services import access, decisions
from helpdesk.services.access import NEEDS, Person
from helpdesk.services.errors import Forbidden, ServiceError
from helpdesk.services.proposals import get
from mcp_governance import run_dir

WHAT = {"reply": "reply on ticket", "close": "close ticket"}


def line(proposal: dict[str, Any]) -> str:
    """#2  close ticket 3 (How do I export my data?), for Sam Rivera"""
    what = f"{WHAT[proposal['kind']]} {proposal['ticket_id']} ({proposal['subject']})"
    flagged = f"  FLAGGED ({len(proposal['flags'])})" if proposal["flags"] else ""
    by = f"filed by {proposal['agent']} for {proposal['proposed_for_name']}"
    return f"#{proposal['id']}  {what}, {by}{flagged}"


def flag_lines(proposal: dict[str, Any]) -> list[str]:
    """What the agent had read that looked like instructions, for the person deciding (chapter 20)."""
    if not proposal["flags"]:
        return []
    lines = ["Flagged: before filing this, the agent read text shaped like instructions:"]
    lines += [f"  {f['source']}: {f['phrase']}" for f in proposal["flags"]]
    lines.append(
        "A flag, not a verdict: approve only what the person it acted for asked for, and what you'd "
        "do anyway."
    )
    return lines


def run_list(conn: Any, person: Person) -> int:
    queue = decisions.queue(conn, person)
    print(f"For {person.label} to decide: {len(queue.theirs) or 'nothing'}")
    for proposal in queue.theirs:
        print(f"  {line(proposal)}")
    if queue.others:
        print(f"Waiting for someone else: {len(queue.others)}")
        for proposal in queue.others:
            print(f"  {line(proposal)}, needs {NEEDS[proposal['needs']]}")
    return 0


def run_show(conn: Any, person: Person, proposal_id: int, who: str) -> int:
    proposal = get(conn, person, proposal_id)
    print(f"#{proposal['id']}: {WHAT[proposal['kind']]} {proposal['ticket_id']}, {proposal['subject']}")
    print(f"Filed by the {proposal['agent']} agent, acting for {proposal['proposed_for_name']}.")
    print(f"Needs the approval of {NEEDS[proposal['needs']]}. Status: {proposal['status']}.")
    if proposal["status"] == "rejected":
        print(f"Rejected by {proposal['decided_by_name']}: {proposal['reason']}")
    elif proposal["status"] == "approved":
        print(f"Approved by {proposal['decided_by_name']}.")
    for flagged in flag_lines(proposal):
        print(flagged)
    if proposal["kind"] == "reply":
        try:
            print(f"To: {decisions.recipient(conn, person, proposal_id)}")
        except Forbidden as e:
            print(e)
        print()
        print(textwrap.fill(proposal["text"], 100))
    else:
        print(f"Why: {proposal['text']}")
    if proposal["status"] == "pending":
        command = f"python -m helpdesk.approvals {{}} {proposal_id} --as {who}"
        print(f"\nApprove: {command.format('approve')}")
        print(f'Reject:  {command.format("reject")} --reason "what to change"')
    return 0


def run_log(conn: Any) -> int:
    rows = [("time", "event", "#", "ticket", "who", "detail")]
    for r in decisions.log(conn):
        who = f"{r['agent']} for {r['staff_name']}" if r["agent"] else r["staff_name"]
        detail = r["detail"] if len(r["detail"]) <= 60 else r["detail"][:57] + "..."
        number = str(r["proposal_id"]) if r["proposal_id"] else "-"
        ticket = str(r["ticket_id"]) if r["ticket_id"] else "-"
        rows.append((r["at"][11:19], r["event"], number, ticket, who, detail))
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:5])) + "  " + row[5])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.approvals")
    parser.add_argument("--db", type=Path, help="the helpdesk database (default: .run/helpdesk.db)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "show", "approve", "reject"):
        command = commands.add_parser(name)
        command.add_argument("--as", dest="person", required=True, help="who is deciding: sam, dana or priya")
        if name != "list":
            command.add_argument("proposal_id", type=int)
        if name == "reject":
            command.add_argument("--reason", required=True, help="what to change: the assistant reads it")
    commands.add_parser("log")
    args = parser.parse_args(argv)

    path = args.db or run_dir() / "helpdesk.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        init_schema(conn)
        if not is_seeded(conn):
            seed(conn)
        if args.command == "log":
            return run_log(conn)
        person = access.find_person(conn, args.person)
        if args.command == "list":
            return run_list(conn, person)
        if args.command == "show":
            return run_show(conn, person, args.proposal_id, args.person)
        if args.command == "approve":
            done = decisions.approve(conn, person, args.proposal_id)
            print(f"Approved #{args.proposal_id}: {done}.")
        else:
            decisions.reject(conn, person, args.proposal_id, args.reason)
            ticket_id = get(conn, person, args.proposal_id)["ticket_id"]
            print(
                f"Rejected #{args.proposal_id}. The assistant reads why the next time it looks at "
                f"ticket {ticket_id}."
            )
        return 0
    except ServiceError as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
