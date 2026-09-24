from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from agent_policy import TODAY_VARIABLE
from helpdesk.api.app import create_app
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed

# Chapter 20: the policy checks models' retirement dates as of a day. The tests fix the day, and
# the programs they start inherit it, so the suite passes on any date; python -m agent_policy in
# node check.mjs leaves it unset and checks as of today.
TODAY = "2026-09-24"
os.environ[TODAY_VARIABLE] = TODAY


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
