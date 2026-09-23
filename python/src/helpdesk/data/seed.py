"""Fictional sample data, so the helpdesk has something in it on first run. Every name is invented."""

from __future__ import annotations

import sqlite3

CUSTOMERS = [
    (1, "Ada Park", "ada.park@example.com"),
    (2, "Ben Okafor", "ben.okafor@example.com"),
    (3, "Chloe Varga", "chloe.varga@example.com"),
]

STAFF = [
    (1, "Sam Rivera", "support"),
    (2, "Dana Whitfield", "lead"),
]

# Tabular sample data: kept one row per block for readability.
# fmt: off
# id, customer_id, subject, body, status, priority, assignee_id, created_at, closed_at
TICKETS = [
    (
        1, 1, "Cannot reset my password", "The reset email never arrives.",
        "open", "high", None, "2026-09-01T09:00:00+00:00", None,
    ),
    (
        2, 2, "Invoice shows the wrong plan", "I downgraded last month but was billed for Pro.",
        "open", "normal", 1, "2026-09-02T14:30:00+00:00", None,
    ),
    (
        3, 3, "How do I export my data?", "Looking for a CSV export of all projects.",
        "pending", "low", 1, "2026-09-03T11:15:00+00:00", None,
    ),
    (
        4, 1, "App crashes on login", "Fixed after the last update, thanks.",
        "closed", "normal", 2, "2026-08-20T08:00:00+00:00", "2026-08-21T16:45:00+00:00",
    ),
]

# id, title, body, tags
KB_ARTICLES = [
    (
        1, "Resetting your password",
        "Use the Forgot password link. Reset emails can take up to ten minutes; check spam.",
        "account,password,login",
    ),
    (
        2, "Changing your plan",
        "Plan changes take effect at the next billing date. Refunds are not automatic.",
        "billing,plan,invoice",
    ),
    (
        3, "Exporting your data",
        "Settings, then Export, produces a CSV of every project you own.",
        "export,csv,data",
    ),
]
# fmt: on


def is_seeded(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM customers LIMIT 1").fetchone() is not None


def seed(conn: sqlite3.Connection) -> None:
    """Load the sample data. Safe to run on a fresh database only."""
    conn.executemany("INSERT INTO customers (id, name, email) VALUES (?, ?, ?)", CUSTOMERS)
    conn.executemany("INSERT INTO staff (id, name, role) VALUES (?, ?, ?)", STAFF)
    conn.executemany(
        "INSERT INTO tickets (id, customer_id, subject, body, status, priority, assignee_id, "
        "created_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        TICKETS,
    )
    conn.executemany("INSERT INTO kb_articles (id, title, body, tags) VALUES (?, ?, ?, ?)", KB_ARTICLES)
    conn.commit()
