"""Fitness function: only the gateway builds a provider's client (chapter 27).

A model call that skips the gateway skips everything it does: the team's budget and rate limits, the
routes, and the record that attributes the call's cost. Nothing in the call itself looks different,
so a missing call is found only when someone compares the record with the provider's bill. This
reads the source instead and fails on any place outside helpdesk/gateway.py that builds the lab's
provider client, or the vendor's own.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
# The one place a provider's client is built, and the adapter that defines it.
ALLOWED = {"helpdesk/gateway.py", "helpdesk/model/anthropic_client.py"}
BUILDERS = {"AnthropicModel", "Anthropic", "AsyncAnthropic"}


def builds_a_client(source: str) -> list[int]:
    """Lines that call AnthropicModel(...) or the SDK's Anthropic(...), under any import name."""
    tree = ast.parse(source)
    names = set(BUILDERS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname for alias in node.names if alias.name in BUILDERS and alias.asname}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = (
                node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            )
            if called in names:
                found.append(node.lineno)
    return sorted(found)


def test_the_check_finds_a_client_built_under_any_name():
    assert builds_a_client(
        "from helpdesk.model.anthropic_client import AnthropicModel\nAnthropicModel()\n"
    ) == [2]
    assert builds_a_client("import anthropic\nclient = anthropic.Anthropic()\n") == [2]
    assert builds_a_client("from x import AnthropicModel as Model\nModel(client=None)\n") == [2]
    assert builds_a_client("model = gateway.for_agent(definition)\n") == []


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
