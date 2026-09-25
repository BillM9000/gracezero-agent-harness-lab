"""Use cases, and the central team's path for them to production (chapter 28).

A use case is a TOML file in the usecases folder: what a team wants an agent for, its answers to
the intake questions, what it needs from the platform, how far it has got, and who signed it off.
usecases/rubric.toml turns the answers into a tier, usecases/readiness.toml lists what each tier
must show before production, and usecases/library.toml is the capability library a use case builds
on. readiness.rules applies them; python -m helpdesk.readiness gathers the evidence and prints.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

USE_CASES = Path(__file__).resolve().parents[2] / "usecases"
RUBRIC = USE_CASES / "rubric.toml"
READINESS = USE_CASES / "readiness.toml"
LIBRARY = USE_CASES / "library.toml"
# The files in the usecases folder that aren't use cases.
NOT_USE_CASES = (RUBRIC.name, READINESS.name, LIBRARY.name)


def load(path: Path) -> dict[str, Any]:
    """Parse one TOML file. Raises tomllib.TOMLDecodeError, with the line, if it isn't valid TOML."""
    return tomllib.loads(path.read_text(encoding="utf-8"))
