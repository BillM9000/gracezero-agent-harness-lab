"""Composition root: the one module that wires every layer together.

Run the service with:  uvicorn --factory helpdesk.main:create_default_app
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from helpdesk.api.app import create_app
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import is_seeded, seed


def build_app(db_path: str = "helpdesk.db", with_sample_data: bool = True) -> FastAPI:
    conn = connect(db_path)
    init_schema(conn)
    if with_sample_data and not is_seeded(conn):
        seed(conn)
    # This module opened the connection, so it hands over the job of closing it.
    return create_app(conn, on_shutdown=conn.close)


def create_default_app() -> FastAPI:
    """Reads HELPDESK_DB; defaults to helpdesk.db in the working directory."""
    return build_app(os.environ.get("HELPDESK_DB", "helpdesk.db"))
