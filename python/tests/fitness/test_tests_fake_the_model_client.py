"""Fitness function: tests build the real model client only around a fake (chapter 15).

AGENTS.md rule 4 says tests never call a real model. The Anthropic client finds saved credentials on
its own, so a test that builds AnthropicModel without handing it a fake client could make a real,
billed call. This walks every test module's syntax tree for that, following import aliases that a
text search would miss.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]


def unfaked_model_clients(source: str) -> list[int]:
    """Lines where AnthropicModel is built with no client, or with client=None."""
    tree = ast.parse(source)
    names = {"AnthropicModel"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname for alias in node.names if alias.name == "AnthropicModel" and alias.asname}
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called = node.func.id
        elif isinstance(node.func, ast.Attribute):
            called = node.func.attr
        else:
            continue
        if called not in names:
            continue
        keyword = next((kw.value for kw in node.keywords if kw.arg == "client"), None)
        given = node.args[0] if node.args else keyword
        if given is None or (isinstance(given, ast.Constant) and given.value is None):
            lines.append(node.lineno)
    return lines


def test_no_test_builds_the_real_model_client_without_a_fake():
    found = {
        path.relative_to(TESTS).as_posix(): lines
        for path in sorted(TESTS.rglob("*.py"))
        if (lines := unfaked_model_clients(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        f"These tests build AnthropicModel without a fake client, so they could call the real API: {found}. "
        "Hand it a fake, as tests/test_anthropic_client.py does: AnthropicModel(FakeClient(...))."
    )


def test_a_client_built_without_a_fake_is_caught():
    source = "from helpdesk.model.anthropic_client import AnthropicModel\nmodel = AnthropicModel()\n"
    assert unfaked_model_clients(source) == [2]


def test_client_none_is_not_a_fake():
    assert unfaked_model_clients("AnthropicModel(client=None)\n") == [1]


def test_an_import_alias_does_not_hide_it():
    source = (
        "from helpdesk.model.anthropic_client import AnthropicModel as Model\n"
        "Model(model='claude-opus-5-5')\n"
    )
    assert unfaked_model_clients(source) == [2]


def test_a_fake_client_passes_however_it_is_given():
    source = "AnthropicModel(FakeClient(None))\nAnthropicModel(client=FakeClient(None))\n"
    assert unfaked_model_clients(source) == []
