from __future__ import annotations

from fastapi.testclient import TestClient

from helpdesk.main import build_app


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_list_tickets(client):
    response = client.get("/tickets")
    assert response.status_code == 200
    assert len(response.json()) == 4


def test_create_ticket_returns_201(client):
    response = client.post("/tickets", json={"customer_id": 1, "subject": "Hi", "body": "Hello"})
    assert response.status_code == 201
    assert response.json()["status"] == "open"


def test_unknown_ticket_is_404_with_a_readable_error(client):
    response = client.get("/tickets/999")
    assert response.status_code == 404
    assert response.json() == {"error": "ticket 999 does not exist"}


def test_an_id_too_big_for_sqlite_is_one_that_does_not_exist(client):
    # SQLite stores an integer in at most 8 bytes; a larger id used to end in a 500 (chapter 3).
    huge = 10**20
    response = client.get(f"/tickets/{huge}")
    assert (response.status_code, response.json()) == (404, {"error": f"ticket {huge} does not exist"})
    new = {"customer_id": huge, "subject": "Hello", "body": "Hi.", "priority": "normal"}
    response = client.post("/tickets", json=new)
    assert (response.status_code, response.json()) == (422, {"error": f"customer {huge} does not exist"})
    response = client.post("/tickets/1/close", json={"staff_id": huge})
    assert response.status_code == 422
    assert client.get("/tickets/1").json()["status"] == "open"


def test_reply_to_closed_ticket_is_409(client):
    response = client.post("/tickets/4/replies", json={"author_kind": "customer", "body": "Hello?"})
    assert response.status_code == 409


def test_close_requires_staff(client):
    response = client.post("/tickets/1/close", json={"staff_id": 99})
    assert response.status_code == 422
    assert "only staff can close tickets" in response.json()["error"]


def test_close_by_staff(client):
    response = client.post("/tickets/1/close", json={"staff_id": 1})
    assert response.status_code == 200
    assert response.json()["status"] == "closed"


def test_malformed_payload_is_422(client):
    response = client.post("/tickets", json={"customer_id": 1, "subject": "", "body": "x"})
    assert response.status_code == 422


def test_kb_search(client):
    response = client.get("/kb/search", params={"q": "export"})
    assert [a["id"] for a in response.json()] == [3, 8, 14]


def test_build_app_seeds_a_fresh_database_once(tmp_path):
    # The "with" block runs the app's startup and shutdown, and shutdown closes the connection.
    # pytest turns an unclosed connection's ResourceWarning into a failure, so a leak fails here.
    db = str(tmp_path / "helpdesk.db")
    with TestClient(build_app(db)) as client:
        assert len(client.get("/tickets").json()) == 4
    with TestClient(build_app(db)) as client:
        assert len(client.get("/tickets").json()) == 4
