"""Fitness function: every route that returns data declares its response model (chapter 15).

Chapter 7 made the response models the one place the API's shapes are written down. A route without
one returns whatever its code happens to build, and contracts/openapi.json describes it only as well
as its return annotation does. This walks the syntax tree of every module in the helpdesk rather
than searching its text, because text can mention response_model without declaring it.

A route is a function decorated with an HTTP method, or registered with add_api_route, on any name
the module binds to APIRouter(...) or FastAPI(...): under any name, through an import alias
(`from fastapi import APIRouter as Routes`), through the module (`fastapi.APIRouter()`), or copied
from another such name. Checking only a name spelled `router` let a second router pass unseen.

What the installed FastAPI (0.141.1, checked 2026-09-27) does without response_model: it uses the
function's return annotation as the response model. `-> TicketSummary` filters out fields the model
doesn't have, answers 500 when the value doesn't fit, and puts the model in the OpenAPI schema. But
`-> dict[str, Any]` checks nothing and documents an open object, and no annotation documents
nothing. So this check still asks for response_model= in the decorator, the one place chapter 7
keeps the shapes; a route with a real reason to go without is listed in EXEMPT with the reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

HELPDESK = Path(__file__).resolve().parents[2] / "src" / "helpdesk"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace", "api_route"}
CONSTRUCTORS = {"APIRouter", "FastAPI"}

# Routes allowed to go without a response model, each with its reason, so an exception is a
# decision someone can read rather than a gap nobody noticed.
EXEMPT = {
    "health": "returns a fixed status with no fields a client depends on; its return type describes it",
}


def router_names(tree: ast.Module) -> set[str]:
    """Every name the module binds to APIRouter(...) or FastAPI(...), however they were imported."""
    constructors = set(CONSTRUCTORS)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "fastapi":
            constructors |= {alias.asname or alias.name for alias in node.names if alias.name in CONSTRUCTORS}
        elif isinstance(node, ast.Import):
            modules |= {
                alias.asname or alias.name for alias in node.names if alias.name.split(".")[0] == "fastapi"
            }

    def builds_one(value: ast.expr | None) -> bool:
        if not isinstance(value, ast.Call):
            return False
        func = value.func
        if isinstance(func, ast.Name):
            return func.id in constructors
        return isinstance(func, ast.Attribute) and func.attr in CONSTRUCTORS and _root(func) in modules

    names: set[str] = set()
    grew = True
    while grew:  # a name copied from a router is a router too, in whatever order they're bound
        grew = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
                targets, value = [node.target], node.value
            else:
                continue
            if builds_one(value) or (isinstance(value, ast.Name) and value.id in names):
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in names:
                        names.add(target.id)
                        grew = True
    return names


def _root(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _on_a_router(func: ast.expr, routers: set[str], methods: set[str]) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and func.attr in methods
        and isinstance(func.value, ast.Name)
        and func.value.id in routers
    )


def routes_without_response_model(source: str) -> list[str]:
    """Routes on any router the module builds whose declaration passes no response_model."""
    tree = ast.parse(source)
    routers = router_names(tree)
    missing = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and _on_a_router(decorator.func, routers, HTTP_METHODS)
                    and not any(keyword.arg == "response_model" for keyword in decorator.keywords)
                ):
                    missing.append(node.name)
        elif (
            isinstance(node, ast.Call)
            and _on_a_router(node.func, routers, {"add_api_route"})
            and not any(keyword.arg == "response_model" for keyword in node.keywords)
        ):
            endpoint = node.args[1] if len(node.args) > 1 else None
            endpoint = endpoint or next((k.value for k in node.keywords if k.arg == "endpoint"), None)
            missing.append(endpoint.id if isinstance(endpoint, ast.Name) else f"line {node.lineno}")
    return missing


def stale_exemptions(exempt: dict[str, str], missing: list[str]) -> list[str]:
    """Exemptions for routes that now declare a response model, or no longer exist."""
    return [name for name in exempt if name not in missing]


def test_every_route_that_returns_data_declares_its_response_model():
    missing = [
        name
        for path in sorted(HELPDESK.rglob("*.py"))
        for name in routes_without_response_model(path.read_text(encoding="utf-8"))
    ]
    unexplained = [name for name in missing if name not in EXEMPT]
    assert not unexplained, (
        f"These routes declare no response_model, so FastAPI checks what they return only as well as "
        f"their return annotation says, and contracts/openapi.json may not describe it: "
        f"{', '.join(unexplained)}. Add response_model= to the decorator. If a route returns nothing a "
        "client depends on, add it to EXEMPT with the reason."
    )
    stale = stale_exemptions(EXEMPT, missing)
    assert not stale, (
        f"EXEMPT lists {', '.join(stale)}, which now declares a response model or is gone. Remove it."
    )


def test_the_routes_are_found_at_all():
    # A check that finds no router passes everything: the lab's own router must be seen.
    source = (HELPDESK / "api" / "routes.py").read_text(encoding="utf-8")
    assert router_names(ast.parse(source)) == {"router"}
    assert "health" in routes_without_response_model(source)


PLANTED = """
@router.get("/tickets", response_model=list[TicketSummary])
def list_tickets(): ...

@router.post("/tickets/{ticket_id}/escalate")  # no response_model yet
def escalate(ticket_id: int): ...
"""


def test_a_route_without_a_response_model_is_caught():
    assert routes_without_response_model("router = APIRouter()\n" + PLANTED) == ["escalate"]


def test_an_exemption_that_no_longer_applies_is_reported():
    missing = routes_without_response_model("router = APIRouter()\n" + PLANTED)
    assert stale_exemptions({"list_tickets": "a reason", "escalate": "a reason"}, missing) == ["list_tickets"]


def test_a_comment_that_mentions_response_model_does_not_fool_it():
    # A text search for "response_model" would find the escalate line and let it pass.
    assert "# no response_model yet" in PLANTED
    assert "escalate" in routes_without_response_model("router = APIRouter()\n" + PLANTED)


ALIASED = """
from fastapi import APIRouter as Routes, FastAPI
import fastapi as fa

admin = Routes(prefix="/admin")
reports = fa.APIRouter()
app = FastAPI()
copied = admin

@admin.delete("/tickets/{ticket_id}")
def purge(ticket_id: int): ...

@reports.get("/reports", response_model=list[Report])
def reports_list(): ...

@app.get("/status")
def status(): ...

@copied.patch("/tickets/{ticket_id}")
def edit(ticket_id: int): ...

def export(): ...

reports.add_api_route("/export", export, methods=["GET"])

@cache.get("/not-a-route")
def cached(): ...
"""


def test_a_router_under_any_name_or_import_alias_is_followed():
    # admin through an import alias, reports through the module, app a FastAPI, copied a copy of
    # admin, and export registered without a decorator; cache is not a router.
    assert routes_without_response_model(ALIASED) == ["purge", "status", "edit", "export"]
