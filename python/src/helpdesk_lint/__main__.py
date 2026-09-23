"""python -m helpdesk_lint [path ...]: run the helpdesk's own lint rule (chapter 17).

Checks every .py file under the paths given (default: src/helpdesk, run from the python folder),
except the helpdesk.model package, where final_text reads the text on purpose. Prints one line per
problem, path:line:column: message, then how many files it read and every exception in use, with
its reason. Exits 0 when clean, 1 when there are problems, and 2 when it found no files: a check
that read nothing must not pass.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

from helpdesk_lint.model_text import Exemption, check

EXEMPT_PACKAGE = ("helpdesk", "model")


def python_files(roots: list[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            yield root
        elif root.is_dir():
            yield from sorted(root.rglob("*.py"))


def exempt(path: Path) -> bool:
    parts = path.resolve().parts
    return any(parts[i : i + 2] == EXEMPT_PACKAGE for i in range(len(parts) - 1))


def main(argv: list[str] | None = None) -> int:
    roots = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv)] or [Path("src/helpdesk")]
    files = [path for path in python_files(roots) if not exempt(path)]
    if not files:
        where = ", ".join(root.as_posix() for root in roots)
        print(f"helpdesk_lint: no Python files under {where}, so nothing was checked.", file=sys.stderr)
        return 2
    problems = 0
    used: list[tuple[Path, Exemption]] = []
    for path in files:
        found, exemptions = check(path.read_text(encoding="utf-8"))
        for problem in found:
            print(f"{path.as_posix()}:{problem.line}:{problem.column}: {problem.message}")
        problems += len(found)
        used += [(path, exemption) for exemption in exemptions]
    print(f"helpdesk_lint: checked {len(files)} files: {problems} problem(s), {len(used)} exception(s).")
    for path, exemption in used:
        print(f"  exception at {path.as_posix()}:{exemption.line}: {exemption.reason}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
