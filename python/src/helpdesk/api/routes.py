"""HTTP routes. Routes validate input and call services; they never touch the data layer."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from helpdesk.services import kb, tickets

router = APIRouter()


def get_conn(request: Request) -> sqlite3.Connection:
    return request.app.state.conn


Conn = Depends(get_conn)


class TicketIn(BaseModel):
    customer_id: int
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    priority: Literal["low", "normal", "high"] = "normal"


class ReplyIn(BaseModel):
    author_kind: Literal["customer", "staff", "assistant"]
    author_id: int | None = None
    body: str = Field(min_length=1, max_length=5000)


class CloseIn(BaseModel):
    staff_id: int


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/tickets")
def list_tickets(status: str | None = None, conn: sqlite3.Connection = Conn) -> list[dict[str, Any]]:
    return tickets.list_tickets(conn, status)


@router.post("/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(payload: TicketIn, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return tickets.create_ticket(conn, payload.customer_id, payload.subject, payload.body, payload.priority)


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return tickets.get_ticket(conn, ticket_id)


@router.post("/tickets/{ticket_id}/replies")
def add_reply(ticket_id: int, payload: ReplyIn, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return tickets.add_reply(conn, ticket_id, payload.author_kind, payload.body, payload.author_id)


@router.post("/tickets/{ticket_id}/close")
def close_ticket(ticket_id: int, payload: CloseIn, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return tickets.close_ticket(conn, ticket_id, payload.staff_id)


@router.get("/kb/search")
def search_kb(q: str, limit: int = 5, conn: sqlite3.Connection = Conn) -> list[dict[str, Any]]:
    return kb.search(conn, q, limit)
