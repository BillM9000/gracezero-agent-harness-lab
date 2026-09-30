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


def test_the_contract_says_what_made_it_in_its_first_lines(tmp_path: Path, capsys) -> None:
    # Chapter 7: every generated file names its source and its generator, contracts/openapi.json too.
    target = tmp_path / "openapi.json"
    assert contract.main(["write", str(target)]) == 0
    first = target.read_text(encoding="utf-8").splitlines()[:8]
    [line] = [line for line in first if '"x-generated-by": ' in line]
    assert "python -m helpdesk.contract write" in line and "by hand" in line
    committed = json.loads(
        (Path(__file__).parents[2] / "contracts" / "openapi.json").read_text(encoding="utf-8")
    )
    assert committed["info"]["x-generated-by"] == contract.GENERATED_BY
    # A contract without the line no longer matches the code, and check says where.
    doc = json.loads(target.read_text(encoding="utf-8"))
    del doc["info"]["x-generated-by"]
    target.write_text(contract.render(doc), encoding="utf-8")
    assert contract.main(["check", str(target)]) == 1
    assert "  changed: info" in capsys.readouterr().err


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
