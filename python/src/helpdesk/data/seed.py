"""Fictional sample data, so the helpdesk has something in it on first run. Every name is invented."""

from __future__ import annotations

import re
import sqlite3
from importlib import resources

CUSTOMERS = [
    (1, "Ada Park", "ada.park@example.com"),
    (2, "Ben Okafor", "ben.okafor@example.com"),
    (3, "Chloe Varga", "chloe.varga@example.com"),
    (4, "Dev Mistry", "dev.mistry@example.com"),
    (5, "Elif Kaya", "elif.kaya@example.com"),
]

# Support staff see the tickets assigned to them and the unassigned queue; a lead sees every
# ticket (helpdesk/services/access.py, chapter 11).
STAFF = [
    (1, "Sam Rivera", "support"),
    (2, "Dana Whitfield", "lead"),
    (3, "Priya Nair", "support"),
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
    (
        5, 2, "Can I downgrade mid-month?", "If I move from Pro to Free today, do I lose Pro straight away?",
        "closed", "low", 1, "2026-08-12T10:05:00+00:00", "2026-08-12T15:20:00+00:00",
    ),
    (
        6, 4, "Invite link expired", "My new teammate says the invitation link doesn't work any more.",
        "open", "normal", None, "2026-09-04T08:40:00+00:00", None,
    ),
    (
        7, 5, "Two-step code rejected", "The code from my authenticator app is always rejected.",
        "open", "high", 3, "2026-09-04T09:10:00+00:00", None,
    ),
    (
        8, 3, "Import stops part way", "My spreadsheet import stops after a few hundred rows.",
        "open", "normal", None, "2026-09-05T13:00:00+00:00", None,
    ),
    (
        9, 4, "Where is our data stored?", "Our security team needs to know which region holds our data.",
        "pending", "normal", 3, "2026-09-05T16:45:00+00:00", None,
    ),
    (
        10, 5, "Receipt for August", "I need a receipt for the August payment for our accounts team.",
        "open", "low", None, "2026-09-06T10:30:00+00:00", None,
    ),
    (
        11, 1, "Notifications too frequent", "Can I get a daily summary instead of an email for each change?",
        "open", "low", 1, "2026-09-07T09:15:00+00:00", None,
    ),
    (
        12, 2, "API token stopped working", "Our integration gets 401 errors since this morning.",
        "open", "high", None, "2026-09-08T07:50:00+00:00", None,
    ),
]

# id, ticket_id, author_kind, author_id (a staff id for staff; None otherwise), body, created_at
REPLIES = [
    (
        1, 5, "staff", 1,
        "No: plan changes take effect at the next billing date, and until then you keep Pro.",
        "2026-08-12T11:30:00+00:00",
    ),
    (2, 5, "customer", None, "Thanks, that's clear.", "2026-08-12T15:10:00+00:00"),
    (
        3, 4, "staff", 2,
        "Glad it's working. The fix was in the last update; closing this now.",
        "2026-08-21T16:40:00+00:00",
    ),
    (
        4, 9, "staff", 3,
        "Checking with our infrastructure team and will confirm the region.",
        "2026-09-06T09:00:00+00:00",
    ),
]

# fmt: on

# Knowledge-base articles live one per file in data/kb/, named NN-slug.md, where NN is the article's
# id. Each starts with a "# Title" line and a "tags:" line; the rest is the body, whose "## "
# headings split it into the passages the assistant searches (chapter 9).
KB_FILE = re.compile(r"^(\d+)-[a-z0-9-]+\.md$")


def kb_articles() -> list[tuple[int, str, str, str]]:
    """Every article as (id, title, body, tags), read from data/kb/ in id order."""
    articles = []
    for entry in resources.files("helpdesk.data").joinpath("kb").iterdir():
        match = KB_FILE.match(entry.name)
        if match is None:
            raise ValueError(
                f"data/kb/{entry.name}: name knowledge-base files NN-slug.md, where NN is the id."
            )
        lines = entry.read_text(encoding="utf-8").splitlines()
        if len(lines) < 3 or not lines[0].startswith("# ") or not lines[1].startswith("tags:"):
            raise ValueError(f"data/kb/{entry.name}: start with a '# Title' line, then a 'tags: a, b' line.")
        tags = ",".join(tag.strip() for tag in lines[1].removeprefix("tags:").split(","))
        articles.append((int(match.group(1)), lines[0][2:].strip(), "\n".join(lines[2:]).strip(), tags))
    return sorted(articles)


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
    conn.executemany(
        "INSERT INTO replies (id, ticket_id, author_kind, author_id, body, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        REPLIES,
    )
    conn.executemany("INSERT INTO kb_articles (id, title, body, tags) VALUES (?, ?, ?, ?)", kb_articles())
    conn.commit()
