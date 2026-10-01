"""Fitness function: tests build a real model client only around a fake (chapter 15).

AGENTS.md rule 4 says tests never call a real model. A provider's client finds saved credentials on
its own, so a test that builds AnthropicModel or OpenAIModel without handing it a fake client could
make a real, billed call. This walks every test module's syntax tree for that, following import
aliases that a text search would miss. A second check, below, fails on any real import of a
provider's SDK under tests/, the start of every other way to a real client (anthropic.Anthropic(),
openai.OpenAI(), a class alias, a subclass), which the first check can't see.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
# The lab's own clients (helpdesk.model), one a provider, and the SDKs they're built on.
MODEL_CLIENTS = {"AnthropicModel", "OpenAIModel"}
SDKS = {"anthropic", "openai"}


def unfaked_model_clients(source: str) -> list[int]:
    """Lines where a model client is built with no client, or with client=None."""
    tree = ast.parse(source)
    names = set(MODEL_CLIENTS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname for alias in node.names if alias.name in MODEL_CLIENTS and alias.asname}
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


def test_no_test_builds_a_real_model_client_without_a_fake():
    found = {
        path.relative_to(TESTS).as_posix(): lines
        for path in sorted(TESTS.rglob("*.py"))
        if (lines := unfaked_model_clients(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        f"These tests build a provider's client without a fake, so they could call the real API: {found}. "
        "Hand it a fake, as tests/test_anthropic_client.py and tests/test_openai_client.py do: "
        "AnthropicModel(FakeClient(...)), OpenAIModel(FakeProviderClient(...))."
    )


def test_a_client_built_without_a_fake_is_caught():
    source = "from helpdesk.model.anthropic_client import AnthropicModel\nmodel = AnthropicModel()\n"
    assert unfaked_model_clients(source) == [2]
    source = (
        "from helpdesk.model.openai_client import OpenAIModel\nmodel = OpenAIModel(model='gpt-6.1-sol')\n"
    )
    assert unfaked_model_clients(source) == [2]


def test_client_none_is_not_a_fake():
    assert unfaked_model_clients("AnthropicModel(client=None)\n") == [1]
    assert unfaked_model_clients("OpenAIModel(client=None)\n") == [1]


def test_an_import_alias_does_not_hide_it():
    source = (
        "from helpdesk.model.anthropic_client import AnthropicModel as Model\n"
        "Model(model='claude-opus-5-5')\n"
    )
    assert unfaked_model_clients(source) == [2]


def test_a_fake_client_passes_however_it_is_given():
    source = "AnthropicModel(FakeClient(None))\nOpenAIModel(client=FakeProviderClient([]))\n"
    assert unfaked_model_clients(source) == []


# --- No test imports a provider's SDK at all.
#
# The check above follows the lab's own wrappers. A test can reach an SDK without them:
# anthropic.Anthropic(), openai.OpenAI(), `from openai import OpenAI`, a class alias made by
# assignment (`Client = anthropic.Anthropic`) or a subclass. Each of those starts with an import, and
# no test needs one (the adapter tests hand each adapter a fake), so any real import of either SDK
# under tests/ fails. A string that only mentions one, such as a planted source, isn't an import.

LOADERS = {"import_module", "__import__", "importorskip"}


def _is_sdk(name: str | None) -> bool:
    return bool(name) and name.split(".")[0] in SDKS


def real_sdk_imports(source: str) -> list[int]:
    """Lines that import a provider's SDK: import, from-import, or a loader called with its name."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found = any(_is_sdk(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found = node.level == 0 and _is_sdk(node.module)
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            first = node.args[0] if node.args else None
            found = (
                name in LOADERS
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and _is_sdk(first.value)
            )
        else:
            found = False
        if found:
            lines.append(node.lineno)
    return sorted(lines)


def test_no_test_imports_a_providers_sdk():
    found = {
        path.relative_to(TESTS).as_posix(): lines
        for path in sorted(TESTS.rglob("*.py"))
        if (lines := real_sdk_imports(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        f"These tests import a provider's SDK, which can build a real client and make a billed call: "
        f"{found}. Tests use the mock, or hand an adapter a fake client as tests/test_anthropic_client.py "
        "and tests/test_openai_client.py do; a planted source that mentions an SDK belongs in a string."
    )


def test_every_way_to_reach_the_sdk_starts_with_an_import_that_is_caught():
    # The four the model-client check misses, each planted.
    assert real_sdk_imports("import anthropic\nclient = anthropic.Anthropic()\n") == [1]
    assert real_sdk_imports("from anthropic import Anthropic\nclient = Anthropic()\n") == [1]
    assert real_sdk_imports("import anthropic\nClient = anthropic.Anthropic\nClient()\n") == [1]
    assert real_sdk_imports(
        "from anthropic import Anthropic as A\n\nclass Mine(A):\n    pass\n\nMine()\n"
    ) == [1]
    # The second provider's SDK, the same ways.
    assert real_sdk_imports("import openai\nclient = openai.OpenAI()\n") == [1]
    assert real_sdk_imports("from openai import OpenAI\nclient = OpenAI()\n") == [1]
    assert real_sdk_imports("from openai.types.responses import Response\n") == [1]
    # Inside a function, a submodule, an alias, or loaded by name.
    assert real_sdk_imports("def f():\n    import anthropic.types as t\n    return t\n") == [2]
    assert real_sdk_imports("from anthropic.types import Message\n") == [1]
    assert real_sdk_imports("import importlib\nsdk = importlib.import_module('anthropic')\n") == [2]
    assert real_sdk_imports("sdk = __import__('openai')\n") == [1]
    assert real_sdk_imports("import pytest\nsdk = pytest.importorskip('anthropic')\n") == [2]


def test_a_string_that_mentions_the_sdk_is_not_an_import():
    source = 'PLANTED = "import anthropic\\nclient = anthropic.Anthropic()\\n"\nNAME = "openai"\n'
    assert real_sdk_imports(source) == []
    # Nor is a module whose name only starts with the same letters, or a relative import.
    assert real_sdk_imports("import anthropic_stub\nimport openai_stub\nfrom .anthropic import fake\n") == []
