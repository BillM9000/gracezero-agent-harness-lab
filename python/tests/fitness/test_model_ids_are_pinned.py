"""Fitness function: every model the code or an agent definition names is a pinned model ID that
agents/models.toml tracks (chapter 20).

A model is a dependency you call rather than install, and it has a date after which it stops working.
Anthropic's documentation says each model ID is a pinned snapshot, while the aliases some earlier
models have point at whichever snapshot is newest; OpenAI's models page gives each model its
snapshots and names one the default, and its deprecations page retires snapshots by their dated ids.
So an alias, or an ID nobody recorded, is a component nobody tracks. This reads the Python source
and the agent definitions for anything shaped like a model ID, from any provider the registry has a
section for, and requires each to be in agents/models.toml.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PYTHON = Path(__file__).resolve().parents[2]
REGISTRY = PYTHON / "agents" / "models.toml"
# A model id as each provider writes them: claude-opus-5-5, gpt-6.1-sol, gpt-5-2025-08-07.
MODEL_ID = re.compile(r"\b(?:claude|gpt)-[a-z0-9]+(?:[.-][a-z0-9]+)*")


def unpinned(text: str, known: set[str]) -> list[str]:
    """Each model ID in the text that the registry doesn't know, with its line."""
    return [
        f"line {n}: {found}"
        for n, line in enumerate(text.splitlines(), 1)
        for found in MODEL_ID.findall(line)
        if found not in known
    ]


def known_models() -> set[str]:
    """Every model in every provider's section of the registry."""
    sections = tomllib.loads(REGISTRY.read_text(encoding="utf-8")).values()
    return {model for section in sections for model in section["models"]}


def test_the_check_finds_an_alias():
    # claude-haiku-4-5 is the alias for claude-haiku-4-5-20251001 on Anthropic's models overview, and
    # gpt-5 names whichever snapshot is current where OpenAI's deprecations page retires
    # gpt-5-2025-08-07; gpt-6.1-sol is its own default snapshot on OpenAI's models page.
    assert unpinned('PRICES = {"claude-haiku-4-5": (1.0, 5.0)}', known_models()) == [
        "line 1: claude-haiku-4-5"
    ]
    assert unpinned('PRICES = {"claude-haiku-4-5-20251001": (1.0, 5.0)}', known_models()) == []
    assert unpinned('model = "gpt-5"', known_models()) == ["line 1: gpt-5"]
    assert unpinned('model = "gpt-6.1-sol"  # and gpt-5-2025-08-07.', known_models()) == []


def test_every_model_named_in_the_code_and_the_definitions_is_pinned_and_tracked():
    files = sorted((PYTHON / "src").rglob("*.py"))
    files += [p for p in sorted((PYTHON / "agents").glob("*.toml")) if p != REGISTRY]
    files += sorted((PYTHON / "gateway").glob("*.toml"))  # the gateway demo's routes (chapter 27)
    known = known_models()
    problems = [
        f"{path.relative_to(PYTHON).as_posix()}, {problem}"
        for path in files
        for problem in unpinned(path.read_text(encoding="utf-8"), known)
    ]
    assert not problems, (
        "These name a model that agents/models.toml doesn't track. Use the model's pinned ID from its "
        "provider's models page, not an alias, and add it under that provider's section of "
        "agents/models.toml with its retirement date from the provider's deprecations page:\n  "
        + "\n  ".join(problems)
    )
