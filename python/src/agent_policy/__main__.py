"""python -m agent_policy [file or folder ...]: check agent definitions against the policy (chapter 18).

With no arguments it checks every .toml file in the agents folder except policy.toml and
models.toml; a folder given as an argument is read the same way. It prints one line per violation,
file: field: reason, then how many definitions it checked. Exits 0 when every definition passes, 1
when any breaks the policy, and 2 when it found none to check.

--today YYYY-MM-DD checks as if it were that day, to see which definitions a model's retirement
will stop, and when (chapter 20). Without it, the check uses today's date.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import date
from pathlib import Path

from agent_policy import AGENTS, MODELS, NOT_DEFINITIONS, POLICY, load, today
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
            files += sorted(p for p in root.glob("*.toml") if p.name not in NOT_DEFINITIONS)
        else:
            files.append(root)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_policy")
    parser.add_argument("paths", nargs="*", type=Path, help="definitions or folders (default: agents/)")
    parser.add_argument("--today", type=date.fromisoformat, help="check as if it were this day, YYYY-MM-DD")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    files = definitions(args.paths or [AGENTS])
    if not files:
        print("agent_policy: no agent definitions found, so nothing was checked.", file=sys.stderr)
        return 2
    policy, models = load(POLICY), load(MODELS)
    as_of = args.today or today()
    problems = 0
    for path in files:
        try:
            violations = check(load(path), policy, models, as_of)
        except tomllib.TOMLDecodeError as error:
            print(f"{shown(path)}: isn't valid TOML: {error}")
            problems += 1
            continue
        for violation in violations:
            print(f"{shown(path)}: {violation.path}: {violation.reason}")
        problems += len(violations)
    when = f" as of {as_of.isoformat()}" if args.today else ""
    summary = f"checked {len(files)} definition(s) against {shown(POLICY)}{when}: {problems} problem(s)."
    print(f"agent_policy: {summary}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
