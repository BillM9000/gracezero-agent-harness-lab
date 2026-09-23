"""Plain SQL for the helpdesk. No business rules live here; services own those."""

from __future__ import annotations

import sqlite3
from typing import Any

Row = dict[str, Any]


def _row(r: sqlite3.Row | None) -> Row | None:
    return dict(r) if r is not None else None


def customer_exists(conn: sqlite3.Connection, customer_id: int) -> bool:
    return conn.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone() is not None


def staff_exists(conn: sqlite3.Connection, staff_id: int) -> bool:
    return conn.execute("SELECT 1 FROM staff WHERE id = ?", (staff_id,)).fetchone() is not None


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
) -> int:
    cur = conn.execute(
        "INSERT INTO replies (ticket_id, author_kind, author_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, author_kind, author_id, body, created_at),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_replies(conn: sqlite3.Connection, ticket_id: int) -> list[Row]:
    rows = conn.execute("SELECT * FROM replies WHERE ticket_id = ? ORDER BY id", (ticket_id,)).fetchall()
    return [dict(r) for r in rows]


def close_ticket(conn: sqlite3.Connection, ticket_id: int, closed_at: str) -> None:
    conn.execute("UPDATE tickets SET status = 'closed', closed_at = ? WHERE id = ?", (closed_at, ticket_id))
    conn.commit()


def search_kb(conn: sqlite3.Connection, query: str, limit: int) -> list[Row]:
    # Deliberately naive keyword search. The retrieval chapter replaces it.
    pattern = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM kb_articles WHERE title LIKE ? OR body LIKE ? OR tags LIKE ? ORDER BY id LIMIT ?",
        (pattern, pattern, pattern, limit),
    ).fetchall()
    return [dict(r) for r in rows]
