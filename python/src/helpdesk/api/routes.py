"""HTTP routes. Routes validate input and call services; they never touch the data layer.

The models below are the one place the API's shapes are written down. FastAPI validates every
request and response against them, and contracts/openapi.json is generated from them
(python -m helpdesk.contract), so the contract can't drift from the code without a check failing.
"""

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

Status = Literal["open", "pending", "closed"]
Priority = Literal["low", "normal", "high"]
AuthorKind = Literal["customer", "staff", "assistant"]


# What callers send.
class NewTicket(BaseModel):
    customer_id: int
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    priority: Priority = "normal"


class NewReply(BaseModel):
    author_kind: AuthorKind
    author_id: int | None = None
    body: str = Field(min_length=1, max_length=5000)


class CloseRequest(BaseModel):
    staff_id: int


# What the API returns.
class Reply(BaseModel):
    id: int
    ticket_id: int
    author_kind: AuthorKind
    author_id: int | None
    body: str
    created_at: str


class TicketSummary(BaseModel):
    """A ticket as the list endpoint returns it, without its replies."""

    id: int
    customer_id: int
    subject: str
    body: str
    status: Status
    priority: Priority
    assignee_id: int | None
    created_at: str
    closed_at: str | None


class Ticket(TicketSummary):
    """A single ticket, with its replies."""

    replies: list[Reply]


class KbArticle(BaseModel):
    id: int
    title: str
    body: str
    tags: str


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/tickets", response_model=list[TicketSummary])
def list_tickets(status: str | None = None, conn: sqlite3.Connection = Conn) -> list[dict[str, Any]]:
    return tickets.list_tickets(conn, status)


@router.post("/tickets", status_code=status.HTTP_201_CREATED, response_model=Ticket)
def create_ticket(payload: NewTicket, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return tickets.create_ticket(conn, payload.customer_id, payload.subject, payload.body, payload.priority)


@router.get("/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: int, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return tickets.get_ticket(conn, ticket_id)


@router.post("/tickets/{ticket_id}/replies", response_model=Ticket)
def add_reply(ticket_id: int, payload: NewReply, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return tickets.add_reply(conn, ticket_id, payload.author_kind, payload.body, payload.author_id)


@router.post("/tickets/{ticket_id}/close", response_model=Ticket)
def close_ticket(ticket_id: int, payload: CloseRequest, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return tickets.close_ticket(conn, ticket_id, payload.staff_id)


@router.get("/kb/search", response_model=list[KbArticle])
def search_kb(q: str, limit: int = 5, conn: sqlite3.Connection = Conn) -> list[dict[str, Any]]:
    return kb.search(conn, q, limit)
