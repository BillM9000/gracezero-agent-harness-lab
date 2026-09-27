"""HDK101: code that wants a model's text calls final_text(response), never response.text.

AGENTS.md rule 5 says so because a refusal or a cut-off answer arrives as a normal response with
text of its own; final_text is what tells those apart from a finished answer (chapter 2). This
rule makes the sentence fail the build.

It is an AST visitor. Function by function, it tracks which names hold a model response: the
result of a .complete(...) call, or a parameter annotated ModelResponse, and a name bound to one of
those by a plain alias (r2 = r), the walrus operator (r := ...) or unpacking a tuple written out
(r, n = model.complete(...), 1). It reports a .text read on one of them, and on a .complete(...)
call directly. It can't follow a response through a container, an attribute or another function.
A text search for ".text" would flag block.text and every other object with a text attribute; the
visitor flags only model responses.

A line that reads the text for another reason carries an exception with its reason, on the same
line or on a comment line just above it: `# HDK101: <why>`. An exception with no reason is
HDK102, and one on a line that no longer reads a model's text is HDK103, so exceptions can't
pile up unexplained.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass

READ_THROUGH_FINAL_TEXT = (
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

EXCEPTION = re.compile(r"#\s*HDK101\b:?(.*)")


@dataclass(frozen=True)
class Problem:
    line: int
    column: int
    message: str


@dataclass(frozen=True)
class Exemption:
    """An `# HDK101: <why>` comment: the line it is on, and its reason."""

    line: int
    reason: str


def is_model_response_annotation(annotation: ast.expr | None) -> bool:
    """True for ModelResponse, types.ModelResponse, "ModelResponse" and unions containing one."""
    if annotation is None:
        return False
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name) and node.id == "ModelResponse":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "ModelResponse":
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "ModelResponse" in node.value:
            return True
    return False


def is_complete_call(node: ast.expr | None) -> bool:
    """A call to a method named complete: the ModelClient protocol's one method."""
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "complete"
    )


class ModelTextVisitor(ast.NodeVisitor):
    """Collects every .text read on a model response, as (line, column, name)."""

    def __init__(self) -> None:
        self.scopes: list[set[str]] = [set()]
        self.reads: list[tuple[int, int, str]] = []

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        args = node.args
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
        responses = {a.arg for a in every if a is not None and is_model_response_annotation(a.annotation)}
        self.scopes.append(responses)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._function(node)

    def _responds(self, value: ast.expr | None) -> bool:
        """A model response: a .complete(...) call, or a name that holds one."""
        if is_complete_call(value):
            return True
        return isinstance(value, ast.Name) and any(value.id in scope for scope in self.scopes)

    def _bind(self, target: ast.expr, value: ast.expr | None) -> None:
        """Track a name bound to a response: `r = model.complete(...)`, a plain alias `r2 = r`, and
        each name of a tuple unpacked from a tuple written out (`r, n = model.complete(...), 1`)."""
        if isinstance(target, ast.Name):
            if self._responds(value):
                self.scopes[-1].add(target.id)
        elif (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
        ):
            for t, v in zip(target.elts, value.elts, strict=True):
                self._bind(t, v)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        for target in node.targets:
            self._bind(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.generic_visit(node)
        if isinstance(node.target, ast.Name) and is_model_response_annotation(node.annotation):
            self.scopes[-1].add(node.target.id)
        self._bind(node.target, node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        # The walrus: `if (r := model.complete(...)).stop_reason ...` binds r like an assignment.
        self.generic_visit(node)
        self._bind(node.target, node.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "text" and isinstance(node.ctx, ast.Load):
            if isinstance(node.value, ast.Name) and any(node.value.id in scope for scope in self.scopes):
                self.reads.append((node.lineno, node.col_offset, node.value.id))
            elif is_complete_call(node.value):
                self.reads.append((node.lineno, node.col_offset, "response"))
            elif isinstance(node.value, ast.NamedExpr) and self._responds(node.value.value):
                self.reads.append((node.lineno, node.col_offset, node.value.target.id))
        self.generic_visit(node)


def exemptions(source: str) -> dict[int, Exemption]:
    """Each HDK101 exception comment, keyed by the line it covers: its own line, or the next line
    when the comment stands on a line by itself."""
    found: dict[int, Exemption] = {}
    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        match = EXCEPTION.match(token.string)
        if match is None:
            continue
        line = token.start[0]
        alone = lines[line - 1].strip().startswith("#")
        covered = line + 1 if alone else line
        found[covered] = Exemption(line, match.group(1).strip())
    return found


def check(source: str) -> tuple[list[Problem], list[Exemption]]:
    """The problems in one file, and the exceptions it uses, with their reasons."""
    visitor = ModelTextVisitor()
    visitor.visit(ast.parse(source))
    marked = exemptions(source)
    problems: list[Problem] = []
    for line, column, name in visitor.reads:
        exemption = marked.get(line)
        if exemption is None:
            problems.append(Problem(line, column + 1, READ_THROUGH_FINAL_TEXT.format(name=name)))
    read_lines = {line for line, _, _ in visitor.reads}
    used: list[Exemption] = []
    for covered, exemption in marked.items():
        if covered not in read_lines:
            problems.append(Problem(exemption.line, 1, STALE))
        elif not exemption.reason:
            problems.append(Problem(exemption.line, 1, NO_REASON))
        else:
            used.append(exemption)
    return sorted(problems, key=lambda p: (p.line, p.column)), used
