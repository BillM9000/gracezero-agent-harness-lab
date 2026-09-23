"""Knowledge base search."""

from __future__ import annotations

import sqlite3
from typing import Any

from helpdesk.data import repository
from helpdesk.services.errors import Invalid

MAX_LIMIT = 20


def search(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict[str, Any]]:
    if not query.strip():
        raise Invalid("query must not be empty")
    if not 1 <= limit <= MAX_LIMIT:
        raise Invalid(f"limit must be between 1 and {MAX_LIMIT}; got {limit}")
    return repository.search_kb(conn, query.strip(), limit)
