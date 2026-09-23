from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helpdesk.api.app import create_app
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed


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
