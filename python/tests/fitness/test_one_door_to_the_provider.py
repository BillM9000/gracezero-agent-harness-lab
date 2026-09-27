"""Fitness function: only the gateway builds a provider's client (chapter 27).

A model call that skips the gateway skips everything it does: the team's budget and rate limits, the
routes, and the record that attributes the call's cost. Nothing in the call itself looks different,
so a missing call is found only when someone compares the record with the provider's bill. This
reads the source instead and fails on any place outside helpdesk/gateway.py that builds the lab's
provider client, or the vendor's own.

The vendor's client classes come from the installed SDK, not a list typed here: every class it
exports on its BaseClient, so AnthropicBedrock, AnthropicVertex, AnthropicFoundry, AnthropicAWS,
their async twins and an alias such as Client all count, and a class a new SDK adds counts too. A
name bound to one of them, by an import alias, by assignment (`Maker = anthropic.AnthropicBedrock`)
or by subclassing, is followed. What it can't see: a class reached some other way, such as
getattr(anthropic, name) or a client built inside a function from another package.
"""

from __future__ import annotations

import ast
from pathlib import Path

from helpdesk.model.anthropic_client import sdk_client_classes

SRC = Path(__file__).resolve().parents[2] / "src"
# The one place a provider's client is built, and the adapter that defines it.
ALLOWED = {"helpdesk/gateway.py", "helpdesk/model/anthropic_client.py"}
BUILDERS = {"AnthropicModel"} | sdk_client_classes()
# A bare name counts without an import only when it can't be anything else: Client is also the name
# of a class the lab defines, so it counts as anthropic.Client or once imported under that name.
BARE = {name for name in BUILDERS if "Anthropic" in name}


def _named(node: ast.expr, names: set[str]) -> bool:
    """Whether an expression names a builder: anthropic.Client, Anthropic, or an alias of one."""
    if isinstance(node, ast.Attribute):
        return node.attr in BUILDERS
    return isinstance(node, ast.Name) and node.id in names


def builds_a_client(source: str) -> list[int]:
    """Lines that call AnthropicModel(...) or one of the SDK's client classes, under any name."""
    tree = ast.parse(source)
    names = set(BARE)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname or alias.name for alias in node.names if alias.name in BUILDERS}
    grew = True
    while grew:  # an alias of an alias, or a subclass of one, in whatever order they're written
        grew = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                new = (
                    {t.id for t in targets if isinstance(t, ast.Name)} if _named(node.value, names) else set()
                )
            elif isinstance(node, ast.ClassDef):
                new = {node.name} if any(_named(base, names) for base in node.bases) else set()
            else:
                continue
            if new - names:
                names |= new
                grew = True
    return sorted(
        node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and _named(node.func, names)
    )


def test_the_check_finds_a_client_built_under_any_name():
    assert builds_a_client(
        "from helpdesk.model.anthropic_client import AnthropicModel\nAnthropicModel()\n"
    ) == [2]
    assert builds_a_client("import anthropic\nclient = anthropic.Anthropic()\n") == [2]
    assert builds_a_client("from x import AnthropicModel as Model\nModel(client=None)\n") == [2]
    assert builds_a_client("model = gateway.for_agent(definition)\n") == []
    # A class of the lab's own that shares its name with an SDK alias isn't the SDK's.
    assert builds_a_client("class Client:\n    pass\n\nClient()\n") == []
    assert builds_a_client("from anthropic import Client\nClient()\n") == [2]


def test_the_sdks_client_classes_come_from_the_sdk():
    expected = {"Anthropic", "AsyncAnthropic", "AnthropicBedrock", "AnthropicVertex", "AnthropicFoundry"}
    assert expected | {"AnthropicAWS", "Client"} <= sdk_client_classes()
    assert "AnthropicError" not in sdk_client_classes()


PLANTED = """
import anthropic
from anthropic import AnthropicVertex as Vertex, AsyncAnthropicFoundry

anthropic.AnthropicBedrock()
Vertex(region="us-east5")
AsyncAnthropicFoundry()
anthropic.AnthropicAWS()
anthropic.Client()
Maker = anthropic.AnthropicBedrock
Again = Maker
Again()

class Wrapped(anthropic.Anthropic):
    pass

Wrapped()
anthropic.AnthropicError("not a client")
"""


def test_every_client_the_sdk_exports_is_found_and_aliases_are_followed():
    # The old list (AnthropicModel, Anthropic, AsyncAnthropic, and import aliases) found none of these.
    lines = PLANTED.splitlines()
    found = [lines[n - 1] for n in builds_a_client(PLANTED)]
    assert found == [
        "anthropic.AnthropicBedrock()",
        'Vertex(region="us-east5")',
        "AsyncAnthropicFoundry()",
        "anthropic.AnthropicAWS()",
        "anthropic.Client()",
        "Again()",
        "Wrapped()",
    ]


def test_only_the_gateway_builds_a_provider_client():
    found = [
        f"{path.relative_to(SRC).as_posix()}:{line}"
        for path in sorted(SRC.rglob("*.py"))
        if path.relative_to(SRC).as_posix() not in ALLOWED
        for line in builds_a_client(path.read_text(encoding="utf-8"))
    ]
    assert not found, (
        f"These build a model provider's client outside the gateway: {', '.join(found)}. A call made "
        "through it would skip the team's budget and limits and never reach the record. Get a client "
        "from helpdesk.gateway.for_agent(definition) instead, and pass it on as a ModelClient."
    )
