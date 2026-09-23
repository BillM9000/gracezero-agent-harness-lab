"""python -m agent_policy [file or folder ...]: check agent definitions against the policy (chapter 18).

With no arguments it checks every .toml file in the agents folder except policy.toml itself; a
folder given as an argument is read the same way. It prints one line per violation, file: field:
reason, then how many definitions it checked. Exits 0 when every definition passes, 1 when any
breaks the policy, and 2 when it found none to check.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from agent_policy import AGENTS, POLICY, load
from agent_policy.rules import check


def shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def definitions(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files += sorted(p for p in root.glob("*.toml") if p.name != POLICY.name)
        else:
            files.append(root)
    return files


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    files = definitions([Path(arg) for arg in args] or [AGENTS])
    if not files:
        print("agent_policy: no agent definitions found, so nothing was checked.", file=sys.stderr)
        return 2
    policy = load(POLICY)
    problems = 0
    for path in files:
        try:
            violations = check(load(path), policy)
        except tomllib.TOMLDecodeError as error:
            print(f"{shown(path)}: isn't valid TOML: {error}")
            problems += 1
            continue
        for violation in violations:
            print(f"{shown(path)}: {violation.path}: {violation.reason}")
        problems += len(violations)
    print(f"agent_policy: checked {len(files)} definition(s) against {shown(POLICY)}: {problems} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
