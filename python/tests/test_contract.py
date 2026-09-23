"""The API contract is generated from the code, and `check` says exactly what drifted (chapter 7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpdesk import contract


def test_the_contract_describes_every_route_and_both_ticket_shapes() -> None:
    doc = contract.document()
    routes = {f"{m.upper()} {p}" for p, item in doc["paths"].items() for m in item}
    assert routes == {
        "GET /health",
        "GET /tickets",
        "POST /tickets",
        "GET /tickets/{ticket_id}",
        "POST /tickets/{ticket_id}/replies",
        "POST /tickets/{ticket_id}/close",
        "GET /kb/search",
    }
    schemas = doc["components"]["schemas"]
    assert "replies" in schemas["Ticket"]["required"]
    assert "replies" not in schemas["TicketSummary"]["properties"]


def test_a_freshly_written_contract_passes_the_check(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    assert contract.main(["write", str(target)]) == 0
    assert contract.main(["check", str(target)]) == 0


def test_a_contract_behind_the_code_fails_and_names_the_change(tmp_path: Path, capsys) -> None:
    target = tmp_path / "openapi.json"
    stale = contract.document()
    del stale["components"]["schemas"]["TicketSummary"]["properties"]["closed_at"]
    target.write_text(contract.render(stale), encoding="utf-8")

    assert contract.main(["check", str(target)]) == 1
    err = capsys.readouterr().err
    assert "schema changed: TicketSummary (fields +closed_at)" in err
    assert f"python -m helpdesk.contract write {target}" in err
    assert "Never edit the contract by hand." in err


def test_routes_added_and_removed_are_named() -> None:
    new = contract.document()
    old = json.loads(json.dumps(new))
    old["paths"]["/tickets/{ticket_id}/escalate"] = {"post": {}}
    del old["paths"]["/kb/search"]
    changes = contract.differences(old, new)
    assert "route added: GET /kb/search" in changes
    assert "route removed: POST /tickets/{ticket_id}/escalate" in changes


def test_a_missing_contract_fails_and_says_how_to_create_it(tmp_path: Path, capsys) -> None:
    target = tmp_path / "openapi.json"
    assert contract.main(["check", str(target)]) == 1
    assert f"Create it with: python -m helpdesk.contract write {target}" in capsys.readouterr().err


@pytest.mark.parametrize("args", [[], ["check"], ["publish", "x.json"]])
def test_anything_but_write_or_check_with_a_path_is_a_usage_error(args: list[str]) -> None:
    assert contract.main(args) == 2
