"""Fitness function: nothing the triage assistant can reach can send anything outside the helpdesk
(chapter 20).

An injected ticket can tell the model to send data somewhere, and the model may try. What stops it
is that no tool can: the assistant's tools, and the services and data layer they call, import
nothing that reaches another machine or starts another program. This walks every module in those
three packages and fails on such an import, or on os.system and its kind, naming the file, the line
and what to do. The model client (helpdesk.model), the MCP server and the web service reach the
network on purpose; each sits outside these packages, behind a composition root.

It also fails on a module loaded by name (importlib.import_module or __import__) when the name is
one of those, or isn't written out where it can be read, and on a relative import, which it can't
resolve without knowing the package. What it doesn't do is follow the lab's own imports: a service
that imported helpdesk.mcp_server would reach the network through it and pass. Following them
means the whole import graph, which import-linter already builds (pyproject.toml's contracts,
with include_external_packages): a forbidden contract from these three packages to the modules
below would check it transitively.

It's a tripwire for code, not a network boundary: a deployed service needs egress rules too.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "helpdesk"
# The packages the assistant's tools run: its tools, the services they call and the data layer.
REACHABLE = ("assistant", "services", "data")
# Modules that can reach another machine, or start a program that can.
OUTSIDE = {
    "aiohttp",
    "anthropic",
    "asyncio",
    "ctypes",
    "ftplib",
    "http",
    "httpcore",
    "httpcore2",
    "httpx",
    "httpx2",
    "imaplib",
    "mcp",
    "multiprocessing",
    "poplib",
    "requests",
    "smtplib",
    "socket",
    "ssl",
    "subprocess",
    "telnetlib",
    "urllib",
    "urllib3",
    "webbrowser",
    "websockets",
    "xmlrpc",
}
# Calls that load a module by its name, as a string.
LOADERS = {"import_module", "__import__"}
# Functions of os that start another program.
OS_RUNNERS = {"system", "popen", "startfile"}
OS_PREFIXES = ("exec", "spawn", "posix_spawn")


def ways_out(source: str) -> list[str]:
    """Each import or call in the source that could send something outside, with its line."""
    found = []
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        elif isinstance(node, ast.ImportFrom) and node.level > 0:
            written = "." * node.level + (node.module or "")
            found.append(
                f"line {node.lineno}: a relative import (from {written} import ...), which this check "
                "can't follow: write it as an absolute import"
            )
        for name in names:
            if name.split(".")[0] in OUTSIDE:
                found.append(f"line {node.lineno}: imports {name}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            and (node.func.attr in OS_RUNNERS or node.func.attr.startswith(OS_PREFIXES))
        ):
            found.append(f"line {node.lineno}: calls os.{node.func.attr}")
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id in LOADERS)
            or (isinstance(node.func, ast.Attribute) and node.func.attr in LOADERS)
        ):
            name = node.args[0] if node.args else None
            if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                found.append(f"line {node.lineno}: loads a module by a name this check can't read")
            elif name.value.split(".")[0] in OUTSIDE:
                found.append(f"line {node.lineno}: loads {name.value} by name")
    # ast.walk goes a level at a time, so a call is found after every import: put them in line order.
    return sorted(found, key=lambda way: int(way.split()[1].rstrip(":")))


def test_the_check_finds_every_way_out_it_claims_to():
    planted = "import os\nimport urllib.request\nfrom httpx import post\nos.system('curl x')\n"
    assert ways_out(planted) == [
        "line 2: imports urllib.request",
        "line 3: imports httpx",
        "line 4: calls os.system",
    ]
    assert ways_out("import json\nimport sqlite3\nfrom helpdesk.services import access\n") == []


def test_a_module_loaded_by_name_or_a_relative_import_is_found():
    # A review (2026-09-26) found each of these passed: only import statements with the name written
    # out, absolute, were read.
    planted = (
        "import importlib\n"
        "from importlib import import_module\n"
        "importlib.import_module('urllib.request')\n"
        "import_module('smtplib')\n"
        "__import__('socket')\n"
        "importlib.import_module(name)\n"
        "from . import mcp_server\n"
        "from ..model import anthropic_client\n"
        "importlib.import_module('json')\n"
    )
    assert ways_out(planted) == [
        "line 3: loads urllib.request by name",
        "line 4: loads smtplib by name",
        "line 5: loads socket by name",
        "line 6: loads a module by a name this check can't read",
        "line 7: a relative import (from . import ...), which this check can't follow: write it as an "
        "absolute import",
        "line 8: a relative import (from ..model import ...), which this check can't follow: write it as "
        "an absolute import",
    ]


def test_nothing_the_assistant_can_reach_sends_anything_outside():
    modules = [path for package in REACHABLE for path in sorted((SRC / package).rglob("*.py"))]
    assert len(modules) >= 15, "the packages moved: point REACHABLE at the assistant's code again"
    problems = [
        f"{path.relative_to(SRC.parents[1]).as_posix()}, {way}"
        for path in modules
        for way in ways_out(path.read_text(encoding="utf-8"))
    ]
    assert not problems, (
        "The assistant's tools and the code they call must not reach another machine: an injected "
        "ticket could make the model use it (chapter 20). Put the call behind a composition root, and "
        "give the assistant a tool that files a proposal for a person instead:\n  " + "\n  ".join(problems)
    )
