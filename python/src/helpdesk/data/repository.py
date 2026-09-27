"""Plain SQL for the helpdesk. No business rules live here; services own those."""

from __future__ import annotations

import sqlite3
from typing import Any

Row = dict[str, Any]

# The ids SQLite can store: it keeps an integer in at most 8 bytes, and Python's sqlite3 raises
# OverflowError for any larger one it's asked to look up, such as a 20-digit ticket number a model or a
# caller sends (chapter 3). No row has such an id, so a lookup by one finds nothing, as any other
# missing id does.
IDS = range(-(2**63), 2**63)


def _row(r: sqlite3.Row | None) -> Row | None:
    return dict(r) if r is not None else None


def customer_exists(conn: sqlite3.Connection, customer_id: int) -> bool:
    if customer_id not in IDS:
        return False
    return conn.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone() is not None


def staff_exists(conn: sqlite3.Connection, staff_id: int) -> bool:
    if staff_id not in IDS:
        return False
    return conn.execute("SELECT 1 FROM staff WHERE id = ?", (staff_id,)).fetchone() is not None


def list_staff(conn: sqlite3.Connection) -> list[Row]:
    return [dict(r) for r in conn.execute("SELECT * FROM staff ORDER BY id").fetchall()]


def customer_names(conn: sqlite3.Connection) -> dict[int, str]:
    # Names only: the assistant's tools have no reason to read a customer's email address.
    return {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM customers").fetchall()}


def list_tickets_for_customer(conn: sqlite3.Connection, customer_id: int) -> list[Row]:
    rows = conn.execute("SELECT * FROM tickets WHERE customer_id = ? ORDER BY id", (customer_id,)).fetchall()
    return [dict(r) for r in rows]


def insert_ticket(
    conn: sqlite3.Connection, customer_id: int, subject: str, body: str, priority: str, created_at: str
) -> int:
    cur = conn.execute(
        "INSERT INTO tickets (customer_id, subject, body, priority, created_at) VALUES (?, ?, ?, ?, ?)",
        (customer_id, subject, body, priority, created_at),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> Row | None:
    if ticket_id not in IDS:
        return None
    return _row(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())


def list_tickets(conn: sqlite3.Connection, status: str | None = None) -> list[Row]:
    if status is None:
        rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM tickets WHERE status = ? ORDER BY id", (status,)).fetchall()
    return [dict(r) for r in rows]


def insert_reply(
    conn: sqlite3.Connection,
    ticket_id: int,
    author_kind: str,
    author_id: int | None,
    body: str,
    created_at: str,
    commit: bool = True,
) -> int:
    # commit=False leaves the transaction open, so an approval, its change and its record can be
    # committed together (helpdesk/services/decisions.py).
    cur = conn.execute(
        "INSERT INTO replies (ticket_id, author_kind, author_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, author_kind, author_id, body, created_at),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def list_replies(conn: sqlite3.Connection, ticket_id: int) -> list[Row]:
    rows = conn.execute("SELECT * FROM replies WHERE ticket_id = ? ORDER BY id", (ticket_id,)).fetchall()
    return [dict(r) for r in rows]


def close_ticket(conn: sqlite3.Connection, ticket_id: int, closed_at: str, commit: bool = True) -> None:
    conn.execute("UPDATE tickets SET status = 'closed', closed_at = ? WHERE id = ?", (closed_at, ticket_id))
    if commit:
        conn.commit()


# The approval queue (chapter 19). None of these commit: the services that call them commit a
# proposal or a decision together with its record in the approval log, or not at all.


def begin_decision(conn: sqlite3.Connection) -> None:
    """Start a transaction that holds the database's write lock from its first statement (SQLite's
    BEGIN IMMEDIATE), so a decision's checks and its change see the same tickets: another
    connection's write waits until this one commits or rolls back. A plain BEGIN takes the lock only
    at the first write, after the checks."""
    conn.execute("BEGIN IMMEDIATE")


def customer_email(conn: sqlite3.Connection, customer_id: int) -> str | None:
    # Only helpdesk/services/decisions.py reads this, for a person who may decide where a reply goes.
    row = conn.execute("SELECT email FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return row["email"] if row else None


def insert_proposal(
    conn: sqlite3.Connection,
    kind: str,
    ticket_id: int,
    text: str,
    agent: str,
    proposed_for: int,
    needs: str,
    created_at: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO proposals (kind, ticket_id, text, agent, proposed_for, needs, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, ticket_id, text, agent, proposed_for, needs, created_at),
    )
    return int(cur.lastrowid)


def get_proposal(conn: sqlite3.Connection, proposal_id: int) -> Row | None:
    return _row(conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone())


def list_proposals(conn: sqlite3.Connection, status: str | None = None) -> list[Row]:
    if status is None:
        rows = conn.execute("SELECT * FROM proposals ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM proposals WHERE status = ? ORDER BY id", (status,)).fetchall()
    return [dict(r) for r in rows]


def list_proposals_for_ticket(conn: sqlite3.Connection, ticket_id: int) -> list[Row]:
    rows = conn.execute("SELECT * FROM proposals WHERE ticket_id = ? ORDER BY id", (ticket_id,)).fetchall()
    return [dict(r) for r in rows]


def decide_proposal(
    conn: sqlite3.Connection,
    proposal_id: int,
    status: str,
    decided_by: int,
    reason: str | None,
    decided_at: str,
) -> bool:
    """Mark a pending proposal decided. False if it wasn't pending, so it can't be decided twice."""
    cur = conn.execute(
        "UPDATE proposals SET status = ?, decided_by = ?, reason = ?, decided_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (status, decided_by, reason, decided_at, proposal_id),
    )
    return cur.rowcount == 1


def insert_log(
    conn: sqlite3.Connection,
    at: str,
    event: str,
    staff_id: int,
    detail: str,
    proposal_id: int | None = None,
    ticket_id: int | None = None,
    agent: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO approval_log (at, event, proposal_id, ticket_id, agent, staff_id, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (at, event, proposal_id, ticket_id, agent, staff_id, detail),
    )


def list_log(conn: sqlite3.Connection) -> list[Row]:
    return [dict(r) for r in conn.execute("SELECT * FROM approval_log ORDER BY id").fetchall()]


def search_kb(conn: sqlite3.Connection, query: str, limit: int) -> list[Row]:
    # An exact filter for people browsing: the articles whose text contains the query, as typed.
    # The assistant's ranked search over passages is helpdesk.services.retrieval (chapter 9).
    pattern = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM kb_articles WHERE title LIKE ? OR body LIKE ? OR tags LIKE ? ORDER BY id LIMIT ?",
        (pattern, pattern, pattern, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_kb_articles(conn: sqlite3.Connection) -> list[Row]:
    return [dict(r) for r in conn.execute("SELECT * FROM kb_articles ORDER BY id").fetchall()]
