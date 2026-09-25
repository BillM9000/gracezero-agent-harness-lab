"""The golden path (chapter 29): the supported way for a team to start a use case.

The golden-path folder holds what the path gives: template.toml (the model, limits and tools, the
intake answers, the platform's standard text and the golden state's checks) and the two files it
writes, agent.tmpl and usecase.tmpl. golden_path.rules renders them and applies the golden state;
python -m helpdesk.golden_path writes a new use case, checks the path on every change, and reports
which use cases are on it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "golden-path"
TEMPLATE = GOLDEN_PATH / "template.toml"
AGENT_TEMPLATE = GOLDEN_PATH / "agent.tmpl"
USE_CASE_TEMPLATE = GOLDEN_PATH / "usecase.tmpl"


def load(path: Path) -> dict[str, Any]:
    """Parse one TOML file. Raises tomllib.TOMLDecodeError, with the line, if it isn't valid TOML."""
    return tomllib.loads(path.read_text(encoding="utf-8"))
