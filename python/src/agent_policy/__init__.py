"""Agent definitions, and the platform's policy for them (chapter 18).

An agent definition is a TOML file in the agents folder: which model the agent calls, its limits,
its tools and its system prompt. agents/policy.toml holds the platform's rules as data, and
agents/models.toml the models' lifecycle (chapter 20); agent_policy.rules.check applies them.
python -m agent_policy checks every definition, and the triage assistant checks its own before it
runs.
"""

from __future__ import annotations

import os
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

AGENTS = Path(__file__).resolve().parents[2] / "agents"
POLICY = AGENTS / "policy.toml"
MODELS = AGENTS / "models.toml"
# The files in the agents folder that aren't agent definitions.
NOT_DEFINITIONS = (POLICY.name, MODELS.name)
# Fixes the day the policy checks as of (YYYY-MM-DD). The tests set it, and node check.mjs sets it to
# the latest "read" date in agents/models.toml, one a provider's section (tools/policy-date.mjs), so
# both pass or fail the same way on any day. python -m agent_policy run on its own, the nightly job and
# the assistant leave it unset, so they check as of today.
TODAY_VARIABLE = "AGENT_POLICY_TODAY"


def today() -> date:
    """The day to check model retirement dates against (chapter 20)."""
    fixed = os.environ.get(TODAY_VARIABLE)
    return date.fromisoformat(fixed) if fixed else date.today()


def load(path: Path) -> dict[str, Any]:
    """Parse one TOML file. Raises tomllib.TOMLDecodeError, with the line, if it isn't valid TOML."""
    return tomllib.loads(path.read_text(encoding="utf-8"))
