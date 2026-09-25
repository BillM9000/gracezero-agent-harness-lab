"""A fitness function (chapter 15): every route that returns data declares its response model.

This is the lab's own python/tests/fitness/test_routes_declare_response_models.py, pointed at the
lab's routes from here. A route without a response model returns whatever its code builds: FastAPI
checks nothing, and contracts/openapi.json can't describe it. It walks the syntax tree rather than
searching the text, because text can mention response_model without declaring it. Lines marked
TEMPLATE are the ones to change for a property of your own.

Run it with pytest. The first test checks the real code; the others plant a violation and require
the check to catch it, so the check is seen to fail.
"""

from __future__ import annotations

import ast
from pathlib import Path

# TEMPLATE: the code the property is about.
ROUTES = Path(__file__).resolve().parents[1] / "python" / "src" / "helpdesk" / "api" / "routes.py"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# TEMPLATE: what may go without, each with its reason, so an exception is a decision someone can
# read rather than a gap nobody noticed.
EXEMPT = {
    "health": "returns a fixed status with no fields a client depends on; its return type describes it",
}


def routes_without_response_model(source: str) -> list[str]:
    """TEMPLATE: the property. Here, functions decorated with @router.<method>(...) whose decorator
    passes no response_model."""
    missing = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in HTTP_METHODS
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "router"
                and not any(keyword.arg == "response_model" for keyword in decorator.keywords)
            ):
                missing.append(node.name)
    return missing


def stale_exemptions(exempt: dict[str, str], missing: list[str]) -> list[str]:
    """Exemptions for routes that now declare a response model, or no longer exist."""
    return [name for name in exempt if name not in missing]


def test_every_route_that_returns_data_declares_its_response_model():
    missing = routes_without_response_model(ROUTES.read_text(encoding="utf-8"))
    unexplained = [name for name in missing if name not in EXEMPT]
    # TEMPLATE: the message says what's wrong, why it matters, how to fix it, and where an
    # exception goes.
    assert not unexplained, (
        f"These routes declare no response_model, so FastAPI doesn't check what they return and "
        f"contracts/openapi.json can't describe it: {', '.join(unexplained)}. Add response_model= to the "
        "decorator. If a route returns nothing a client depends on, add it to EXEMPT with the reason."
    )
    stale = stale_exemptions(EXEMPT, missing)
    assert not stale, (
        f"EXEMPT lists {', '.join(stale)}, which now declares a response model or is gone. Remove it."
    )


# TEMPLATE: a violation planted in a copy, so the check is seen to fail.
PLANTED = """
@router.get("/tickets", response_model=list[TicketSummary])
def list_tickets(): ...

@router.post("/tickets/{ticket_id}/escalate")  # no response_model yet
def escalate(ticket_id: int): ...
"""


def test_a_route_without_a_response_model_is_caught():
    assert routes_without_response_model(PLANTED) == ["escalate"]


def test_an_exemption_that_no_longer_applies_is_reported():
    missing = routes_without_response_model(PLANTED)
    assert stale_exemptions({"list_tickets": "a reason", "escalate": "a reason"}, missing) == ["list_tickets"]


def test_a_comment_that_mentions_response_model_does_not_fool_it():
    # A text search for "response_model" would find the escalate line and let it pass.
    assert "# no response_model yet" in PLANTED
    assert "escalate" in routes_without_response_model(PLANTED)
