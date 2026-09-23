"""Fitness function, holistic: no read route returns a customer's email address (chapter 15).

The routes, the services, the data layer and the response models all decide what a response
contains, so no single file shows this property. This runs the whole app on the sample data, calls
every GET route the app itself describes, and searches each response for any customer's email.
A route added later is checked without anyone remembering to add it, because the list comes from
the app.
"""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpdesk.api.app import create_app

# A sample value for each parameter a GET route requires. A new required parameter needs one here.
SAMPLES = {"ticket_id": "1", "q": "password"}


def routes_returning(app: FastAPI, secrets: list[str]) -> list[str]:
    """The GET routes whose response, given sample parameters, contains any of the secrets."""
    found = []
    client = TestClient(app)
    for path, item in app.openapi()["paths"].items():
        operation = item.get("get")
        if operation is None:
            continue
        required = [p for p in operation.get("parameters", []) if p.get("required")]
        unknown = [p["name"] for p in required if p["name"] not in SAMPLES]
        assert not unknown, f"GET {path} requires {unknown}; add a sample value to SAMPLES to check it."
        url = re.sub(r"\{(\w+)\}", lambda m: SAMPLES[m.group(1)], path)
        query = {p["name"]: SAMPLES[p["name"]] for p in required if p["in"] == "query"}
        text = client.get(url, params=query).text
        if any(secret in text for secret in secrets):
            found.append(f"GET {path}")
    return found


def customer_emails(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT email FROM customers ORDER BY id")]


def test_no_read_route_returns_a_customer_email(conn):
    leaks = routes_returning(create_app(conn), customer_emails(conn))
    assert not leaks, (
        f"These routes return a customer's email address: {leaks}. Tickets name customers by id; if a "
        "staff screen needs the email, give it a route that checks who is asking (chapter 19)."
    )


def test_a_route_that_leaks_an_email_is_caught(conn):
    app = create_app(conn)
    emails = customer_emails(conn)
    app.add_api_route("/customers/first", lambda: {"email": emails[0]}, methods=["GET"])
    assert routes_returning(app, emails) == ["GET /customers/first"]
