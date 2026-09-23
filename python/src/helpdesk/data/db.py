"""SQLite connection and schema setup. The only module that knows the database is SQLite."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database with rows addressable by column name and foreign keys enforced."""
    # check_same_thread=False: the web framework may call from worker threads. One writer, lab scale.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    schema = resources.files("helpdesk.data").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
