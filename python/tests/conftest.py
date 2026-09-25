from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from agent_policy import TODAY_VARIABLE
from helpdesk.api.app import create_app
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed

# Chapter 20: the policy checks models' retirement dates as of a day. The tests fix the day, and
# the programs they start inherit it, so the suite passes on any date. node check.mjs fixes it for
# its other checks too (tools/policy-date.mjs); python -m agent_policy on its own checks as of today.
TODAY = "2026-09-24"
os.environ[TODAY_VARIABLE] = TODAY


@pytest.fixture(autouse=True)
def gateway_record(tmp_path, monkeypatch):
    """Chapter 27: a test that builds the real client with a fake goes through the lab's gateway,
    which records every call. Each test gets its own record and its own gateway, so no test's calls
    count against another's team budget, and none lands in the repository's records/ folder."""
    from helpdesk import gateway

    path = tmp_path / "gateway-record" / "gateway.jsonl"
    monkeypatch.setenv(gateway.RECORD_VARIABLE, str(path))
    gateway._GATEWAYS.clear()
    yield path
    gateway._GATEWAYS.clear()


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "helpdesk-test.db")
    init_schema(connection)
    seed(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(conn):
    return TestClient(create_app(conn))
