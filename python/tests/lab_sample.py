"""The lab's own agent definitions and use cases, which some tests pin by count (chapters 18, 28, 29).

python -m helpdesk.golden_path new writes a team's agent definition and use case into agents/ and
usecases/, beside these, and they pass the platform's checks there from their first commit (chapter
29's Try it starts one). The tests that count the lab's definitions or use cases read a copy of the two
folders holding only the files named here, so a use case a reader has started changes none of their
results, and they still pass with it in place.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from agent_policy import AGENTS
from readiness import USE_CASES

DEFINITIONS = ("judge-second.toml", "judge.toml", "orchestrator.toml", "triage.toml")
AGENT_FILES = (*DEFINITIONS, "models.toml", "policy.toml")
USE_CASE_FILES = (
    "customer-digest.toml",
    "library.toml",
    "readiness.toml",
    "renewal-reminders.toml",
    "rubric.toml",
    "triage-assistant.toml",
)


def copy(to: Path, agents: Path = AGENTS, use_cases: Path = USE_CASES) -> tuple[Path, Path]:
    """Copies of the lab's own files from agents/ and usecases/, in to/agents and to/usecases."""
    copies = []
    for source, names, folder in ((agents, AGENT_FILES, "agents"), (use_cases, USE_CASE_FILES, "usecases")):
        target = to / folder
        target.mkdir(parents=True)
        for name in names:
            shutil.copy2(source / name, target / name)
        copies.append(target)
    return copies[0], copies[1]
