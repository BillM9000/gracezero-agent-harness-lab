"""Agent definitions, and the platform's policy for them (chapter 18).

An agent definition is a TOML file in the agents folder: which model the agent calls, its limits,
its tools and its system prompt. agents/policy.toml holds the platform's rules as data, and
agent_policy.rules.check applies them. python -m agent_policy checks every definition, and the
triage assistant checks its own before it runs.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

AGENTS = Path(__file__).resolve().parents[2] / "agents"
POLICY = AGENTS / "policy.toml"


def load(path: Path) -> dict[str, Any]:
    """Parse one TOML file. Raises tomllib.TOMLDecodeError, with the line, if it isn't valid TOML."""
    return tomllib.loads(path.read_text(encoding="utf-8"))
