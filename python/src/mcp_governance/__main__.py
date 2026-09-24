"""python -m mcp_governance: the catalog of approved MCP servers, and the audit log (chapter 13).

python -m mcp_governance [check] [file or folder ...]
    Check catalogs against the rules (catalog/policy.toml). With no files, the organization's own,
    catalog/servers.toml; a folder is read as a set of catalogs, as tests/catalog_fixtures/ is. One
    line per violation, file: field: reason. Exits 0 when all pass, 1 when any breaks a rule, and 2
    when it found nothing to check.
python -m mcp_governance allowlist
    Print catalog/servers.toml as the allowlist a host's managed settings enforce. Refuses a catalog
    that breaks the rules.
python -m mcp_governance audit [--log PATH]
    Print the audit log the helpdesk's MCP server writes over HTTP: who called what, for whom, and
    what came of it. The log is .run/audit.jsonl unless HELPDESK_RUN_DIR moves it.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from mcp_governance import POLICY, SERVERS, audit, load, run_dir
from mcp_governance.catalog import allowlist, check


def shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def catalogs(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files += sorted(p for p in root.glob("*.toml") if p.name != POLICY.name) if root.is_dir() else [root]
    return files


def check_command(paths: list[str]) -> int:
    files = catalogs([Path(p) for p in paths] or [SERVERS])
    if not files:
        print("mcp_governance: no catalogs found, so nothing was checked.", file=sys.stderr)
        return 2
    policy = load(POLICY)
    problems = servers = 0
    for path in files:
        try:
            catalog = load(path)
        except tomllib.TOMLDecodeError as error:
            print(f"{shown(path)}: isn't valid TOML: {error}")
            problems += 1
            continue
        servers += len(catalog.get("servers", [])) if isinstance(catalog.get("servers"), list) else 0
        for violation in check(catalog, policy):
            print(f"{shown(path)}: {violation.path}: {violation.reason}")
            problems += 1
    print(
        f"mcp_governance: checked {servers} server(s) in {len(files)} catalog(s) against "
        f"{shown(POLICY)}: {problems} problem(s)."
    )
    return 1 if problems else 0


def allowlist_command() -> int:
    catalog = load(SERVERS)
    if check(catalog, load(POLICY)):
        print(
            f"Refused: {shown(SERVERS)} breaks the catalog's rules. Run python -m mcp_governance.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(allowlist(catalog), indent=2))
    return 0


def audit_command(log: str | None) -> int:
    path = Path(log) if log else run_dir() / "audit.jsonl"
    records = audit.read(path)
    if not records:
        print(
            f"No audit records in {shown(path)} yet. Start python -m helpdesk.mcp_server --http and call it."
        )
        return 0
    for line in audit.table(records):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["allowlist"]:
        return allowlist_command()
    if args[:1] == ["audit"]:
        parser = argparse.ArgumentParser(prog="python -m mcp_governance audit")
        parser.add_argument("--log", help="the audit log to read (default: .run/audit.jsonl)")
        return audit_command(parser.parse_args(args[1:]).log)
    return check_command(args[1:] if args[:1] == ["check"] else args)


if __name__ == "__main__":
    sys.exit(main())
