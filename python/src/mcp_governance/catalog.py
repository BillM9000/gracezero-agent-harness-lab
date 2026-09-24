"""The catalog of approved MCP servers (chapter 13), and its rules as one pure function, check.

The catalog, catalog/servers.toml, is the organization's list of MCP servers that may run: for each,
who answers for it, how it's reached, the scopes a token for it may carry and exactly the tools it
was approved with. A new server is approved by adding an entry, in a change the platform team
reviews. check applies the rules to every entry and returns every violation, each naming the field,
the reason and the fix, as agent_policy does for agent definitions (chapter 18); the data the rules
use is in catalog/policy.toml, and tests/catalog_fixtures/ shows what they accept and refuse.

Two more things read the catalog. allowlist turns it into the list a host enforces (Claude Code's
managed settings, for one), naming each server by its address or exact command, never by name.
offered_differs compares what a running server offers with its entry, so a server whose tools have
changed since it was approved refuses to start.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlsplit

# Every rule the catalog applies. A test requires each one to be shown failing by some fixture.
RULES = {
    "unknown-field": "a field that catalog entries don't have",
    "missing": "a required field left out",
    "type": "a field of the wrong type",
    "empty": "a text field left empty",
    "name": "a name a host can't use",
    "transport": "a transport other than http or stdio",
    "wrong-transport": "a field that belongs to the other transport",
    "url": "an address that isn't a server's canonical HTTPS address",
    "command": "a stdio command that isn't a program and its arguments",
    "scope": "a missing, malformed, repeated or all-granting scope",
    "tools": "a tool list that's empty, repeated or not names",
    "date": "an approval date that isn't a date",
    "duplicate": "a server listed twice",
}


@dataclass(frozen=True)
class Violation:
    path: str  # the field as the file writes it, such as "servers[0].url"
    rule: str
    reason: str

    def __post_init__(self) -> None:
        if self.rule not in RULES:
            raise ValueError(f"{self.rule!r} isn't in RULES; add it, with a fixture that shows it failing.")


# Every field an entry has, its type, and why the organization needs it. Some belong to one transport.
FIELDS: dict[str, tuple[type, str]] = {
    "name": (str, "Name the server, as hosts and people will refer to it."),
    "owner": (str, "Name the team that answers for the server when it misbehaves."),
    "transport": (str, 'Say how hosts reach it: "http" or "stdio".'),
    "url": (str, "Give the address tokens for it are issued for."),
    "command": (list, "Give the exact command that starts it, program and arguments."),
    "scopes": (list, "List the scopes a token for it may carry."),
    "tools": (list, "List exactly the tools it was approved with."),
    "approved": (str, "Give the date it was approved, as YYYY-MM-DD."),
    "approved_by": (str, "Name who approved it."),
}
COMMON = ["name", "owner", "transport", "tools", "approved", "approved_by"]
BY_TRANSPORT = {"http": ["url", "scopes"], "stdio": ["command"]}
TYPE_NAMES = {str: "text", list: "a list"}
# Claude Code accepts only these characters in the name of a server it's given through managed
# settings, and in an allowlist's name entries.
NAME = re.compile(r"^[A-Za-z0-9_-]+$")
# A scope is one token of printable ASCII without spaces, quotation marks or backslashes (RFC 6750).
SCOPE = re.compile(r"^[\x21\x23-\x5b\x5d-\x7e]+$")


def shown(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def is_a(value: Any, kind: type) -> bool:
    return isinstance(value, kind) and not isinstance(value, bool)


def check(catalog: dict[str, Any], policy: dict[str, Any]) -> list[Violation]:
    found: list[Violation] = []
    servers = catalog.get("servers")
    if not isinstance(servers, list) or not all(isinstance(s, dict) for s in servers):
        return [Violation("servers", "missing", "missing. List each approved server under [[servers]].")]
    for i, server in enumerate(servers):
        found += check_server(f"servers[{i}]", server, policy)

    for field in ("name", "url"):
        seen: dict[str, int] = {}
        for i, server in enumerate(servers):
            value = server.get(field)
            if not isinstance(value, str):
                continue
            key = value.lower().rstrip("/")
            if key in seen:
                reason = (
                    f"{shown(value)} is already servers[{seen[key]}]. List each server once, so its "
                    "approval, scopes and tools are written in one place."
                )
                found.append(Violation(f"servers[{i}].{field}", "duplicate", reason))
            else:
                seen[key] = i
    return found


def check_server(at: str, server: dict[str, Any], policy: dict[str, Any]) -> list[Violation]:
    found: list[Violation] = []
    transport = server.get("transport")
    expected = COMMON + BY_TRANSPORT.get(transport, []) if isinstance(transport, str) else COMMON

    for key in server:
        if key not in FIELDS:
            close = difflib.get_close_matches(key, FIELDS, n=1)
            hint = f"Did you mean {close[0]}?" if close else f"The fields are {', '.join(FIELDS)}."
            found.append(
                Violation(f"{at}.{key}", "unknown-field", f"{key} isn't a field of a server. {hint}")
            )
        elif key not in expected and transport in BY_TRANSPORT:
            other = "stdio" if transport == "http" else "http"
            reason = (
                f"{key} is for {other} servers, and this one is {transport}. An http server is reached "
                "at its url with a token carrying scopes; a stdio server is started with its command "
                "and takes its credentials from its environment."
            )
            found.append(Violation(f"{at}.{key}", "wrong-transport", reason))

    usable: dict[str, Any] = {}
    for key in expected:
        kind, why = FIELDS[key]
        if key not in server:
            found.append(Violation(f"{at}.{key}", "missing", f"missing. {why}"))
        elif not is_a(server[key], kind):
            found.append(
                Violation(f"{at}.{key}", "type", f"must be {TYPE_NAMES[kind]}, not {shown(server[key])}.")
            )
        elif kind is str and not server[key].strip():
            found.append(Violation(f"{at}.{key}", "empty", f"is empty. {why}"))
        else:
            usable[key] = server[key]

    name = usable.get("name")
    if name is not None and not NAME.match(name):
        reason = (
            f"{shown(name)} has characters a host won't take. Use only letters, numbers, hyphens and "
            "underscores."
        )
        found.append(Violation(f"{at}.name", "name", reason))

    if "transport" in usable and usable["transport"] not in policy["transports"]:
        allowed = " or ".join(map(shown, policy["transports"]))
        found.append(Violation(f"{at}.transport", "transport", f"must be {allowed}, not {shown(transport)}."))

    url = usable.get("url")
    if url is not None:
        problem = url_problem(url, policy["local_hosts"])
        if problem:
            found.append(Violation(f"{at}.url", "url", problem))

    command = usable.get("command")
    if command is not None and (not command or not all(is_a(part, str) and part.strip() for part in command)):
        reason = (
            f"{shown(command)} isn't a command. Write the program and each argument as a string, exactly "
            'as hosts will run it, such as ["npx", "-y", "some-server@1.2.3"]: hosts match it exactly.'
        )
        found.append(Violation(f"{at}.command", "command", reason))

    scopes = usable.get("scopes")
    if scopes is not None:
        found += scope_problems(f"{at}.scopes", scopes, policy["omnibus_scopes"])

    tools = usable.get("tools")
    if tools is not None:
        if not tools:
            reason = (
                "is empty. List the tools it was approved with: a server with no tools needs no approval."
            )
            found.append(Violation(f"{at}.tools", "tools", reason))
        for j, tool in enumerate(tools):
            if not is_a(tool, str) or not tool.strip():
                found.append(
                    Violation(f"{at}.tools[{j}]", "tools", f"must be a tool's name, not {shown(tool)}.")
                )
            elif tools.index(tool) != j:
                found.append(Violation(f"{at}.tools[{j}]", "tools", f"{shown(tool)} is listed twice."))

    approved = usable.get("approved")
    if approved is not None:
        try:
            date.fromisoformat(approved)
        except ValueError:
            reason = f"{shown(approved)} isn't a date. Write the day it was approved as YYYY-MM-DD."
            found.append(Violation(f"{at}.approved", "date", reason))
    return found


def url_problem(url: str, local_hosts: list[str]) -> str | None:
    """Why an address can't be a server's, or None. A server's address is what tokens for it name."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    shown_host = f"[{host}]" if ":" in host else host
    if parts.scheme not in ("https", "http") or not host:
        return f"{shown(url)} isn't an address. Give the server's full address, such as https://mcp.example.com/mcp."
    if parts.fragment or "#" in url:
        return f"{shown(url)} has a fragment, which a server's canonical address can't. Leave out the # part."
    if parts.scheme == "http" and shown_host not in local_hosts:
        return (
            f"{shown(url)} isn't HTTPS. Tokens go to this address with every request, so a server "
            "anywhere but this machine must be reached over HTTPS."
        )
    return None


def scope_problems(at: str, scopes: list[Any], omnibus: list[str]) -> list[Violation]:
    found: list[Violation] = []
    if not scopes:
        reason = "is empty. List the scopes a token for it may carry, so a client can ask for less than all."
        return [Violation(at, "scope", reason)]
    for j, scope in enumerate(scopes):
        if not is_a(scope, str) or not SCOPE.match(scope):
            reason = (
                f"{shown(scope)} isn't a scope: one word of printable characters, without spaces or quotes."
            )
            found.append(Violation(f"{at}[{j}]", "scope", reason))
        elif scope.lower() in omnibus:
            reason = (
                f"{shown(scope)} grants everything at once. Name what each scope allows, such as "
                '"tickets:read", so a token can carry only what a task needs.'
            )
            found.append(Violation(f"{at}[{j}]", "scope", reason))
        elif scopes.index(scope) != j:
            found.append(Violation(f"{at}[{j}]", "scope", f"{shown(scope)} is listed twice."))
    return found


def entry(catalog: dict[str, Any], name: str) -> dict[str, Any] | None:
    """The catalog's entry for one server, by name."""
    return next((s for s in catalog.get("servers", []) if s.get("name") == name), None)


def offered_differs(server: dict[str, Any], *, tools: list[str], scopes: list[str]) -> list[str]:
    """How a running server differs from its entry: any tool or scope it offers that wasn't approved,
    and any that was approved and it no longer offers. Empty when they match exactly."""
    problems: list[str] = []
    for kind, offered, approved in (
        ("tool", tools, server.get("tools", [])),
        ("scope", scopes, server.get("scopes", [])),
    ):
        for extra in [x for x in offered if x not in approved]:
            problems.append(
                f"it offers the {kind} {extra}, which the catalog doesn't approve for {server['name']}"
            )
        for gone in [x for x in approved if x not in offered]:
            problems.append(f"the catalog approves the {kind} {gone}, which it doesn't offer")
    return problems


def allowlist(catalog: dict[str, Any]) -> dict[str, Any]:
    """The catalog as the managed settings Claude Code's documentation describes: an allowlist of servers
    matched by address or by exact command, never by name, which anyone can give any server, and locked
    so that users' own settings can't widen it."""
    allowed = [
        {"serverUrl": s["url"]} if s["transport"] == "http" else {"serverCommand": s["command"]}
        for s in catalog["servers"]
    ]
    return {"allowManagedMcpServersOnly": True, "allowedMcpServers": allowed}
