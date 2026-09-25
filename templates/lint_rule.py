"""A lint rule that teaches, in one file (chapter 17): python lint_rule.py [path ...]

This is the lab's own rule, HDK101 (python/src/helpdesk_lint/), trimmed: code that wants a model's
text calls final_text(response), never response.text, because a refusal or a cut-off answer is a
normal response with text of its own. The lab's version also follows parameters annotated
ModelResponse. Lines marked TEMPLATE are the ones to change for a rule of your own.

It walks each file's syntax tree, so it flags meaning rather than text: response.text is reported,
block.text is not. A line that breaks the rule on purpose says why, in a comment on it or on the line
above: # HDK101: <why>. An exception with no reason fails, and so does one on a line that no longer
breaks the rule, so exceptions can't pile up unexplained.

It prints path:line:column: message for each problem, then how many files it read and every
exception in use, with its reason. Exits 0 when clean, 1 with problems, and 2 when it found no files:
a check that read nothing must not pass.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

# TEMPLATE: the messages. Each says what's wrong, why it matters, what to do instead, and how to
# make an exception, because for an agent the message is the next instruction.
MESSAGE = (
    "HDK101 Read the model's text with final_text({name}), not {name}.text. A refusal or a cut-off "
    "answer is a normal response with text of its own, and final_text is what tells them apart from "
    "a finished answer (AGENTS.md rule 5). If this line keeps the text for another reason, such as "
    "recording the turn, put the reason on it: # HDK101: <why>"
)
NO_REASON = (
    "HDK102 This HDK101 exception gives no reason. Say why reading the text here is safe, after the "
    "colon, so the next reader doesn't have to work it out: # HDK101: <why>"
)
STALE = (
    "HDK103 This HDK101 exception is on a line that doesn't read a model's text. Remove the comment; "
    "an exception that no longer applies hides the next real one."
)
# TEMPLATE: the comment that marks an exception, with its reason after the colon.
EXCEPTION = re.compile(r"#\s*HDK101\b:?(.*)")
# TEMPLATE: where to look by default, and the one package allowed to break the rule (here, the
# package where final_text reads the text on purpose).
DEFAULT_PATHS = ["src/helpdesk"]
EXEMPT_PACKAGE = ("helpdesk", "model")


def is_complete_call(node: ast.expr | None) -> bool:
    """A call to a method named complete: the one method every model client in the lab has."""
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "complete"
    )


class Visitor(ast.NodeVisitor):
    """TEMPLATE: what the rule matches. Here, a .text read on a name that holds a .complete(...)
    result, tracked function by function, or on a .complete(...) call itself."""

    def __init__(self) -> None:
        self.scopes: list[set[str]] = [set()]
        self.reads: list[tuple[int, int, str]] = []

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scopes.append(set())
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        if is_complete_call(node.value):
            self.scopes[-1].update(t.id for t in node.targets if isinstance(t, ast.Name))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "text" and isinstance(node.ctx, ast.Load):
            if isinstance(node.value, ast.Name) and any(node.value.id in scope for scope in self.scopes):
                self.reads.append((node.lineno, node.col_offset, node.value.id))
            elif is_complete_call(node.value):
                self.reads.append((node.lineno, node.col_offset, "response"))
        # Keep walking: without this, response.text.strip() would hide the read inside it.
        self.generic_visit(node)


def exceptions(source: str) -> dict[int, tuple[int, str]]:
    """Each exception comment, keyed by the line it covers (its own, or the next when the comment
    stands alone), as (the comment's line, its reason)."""
    found: dict[int, tuple[int, str]] = {}
    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        match = EXCEPTION.match(token.string) if token.type == tokenize.COMMENT else None
        if match:
            line = token.start[0]
            alone = lines[line - 1].strip().startswith("#")
            found[line + 1 if alone else line] = (line, match.group(1).strip())
    return found


def check(source: str) -> tuple[list[tuple[int, int, str]], list[tuple[int, str]]]:
    """One file's problems as (line, column, message), and the exceptions it uses."""
    visitor = Visitor()
    visitor.visit(ast.parse(source))
    marked = exceptions(source)
    problems = [
        (line, col + 1, MESSAGE.format(name=name)) for line, col, name in visitor.reads if line not in marked
    ]
    read_lines = {line for line, _, _ in visitor.reads}
    used = []
    for covered, (line, reason) in marked.items():
        if covered not in read_lines:
            problems.append((line, 1, STALE))
        elif not reason:
            problems.append((line, 1, NO_REASON))
        else:
            used.append((line, reason))
    return sorted(problems), used


def exempt(path: Path) -> bool:
    parts = path.resolve().parts
    return any(parts[i : i + 2] == EXEMPT_PACKAGE for i in range(len(parts) - 1))


def python_files(roots: list[Path]) -> list[Path]:
    """Every .py file under the paths given, except those in the exempt package."""
    found = [root for root in roots if root.is_file() and root.suffix == ".py"]
    found += [path for root in roots if root.is_dir() for path in sorted(root.rglob("*.py"))]
    return [path for path in found if not exempt(path)]


def main(argv: list[str]) -> int:
    roots = [Path(arg) for arg in argv or DEFAULT_PATHS]
    files = python_files(roots)
    if not files:
        where = ", ".join(root.as_posix() for root in roots)
        print(f"lint_rule: no Python files under {where}, so nothing was checked.", file=sys.stderr)
        return 2
    count = 0
    used = []
    for path in files:
        problems, exempted = check(path.read_text(encoding="utf-8"))
        for line, column, message in problems:
            print(f"{path.as_posix()}:{line}:{column}: {message}")
        count += len(problems)
        used += [(path, line, reason) for line, reason in exempted]
    print(f"lint_rule: checked {len(files)} files: {count} problem(s), {len(used)} exception(s).")
    for path, line, reason in used:
        print(f"  exception at {path.as_posix()}:{line}: {reason}")
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
