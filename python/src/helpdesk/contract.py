"""The helpdesk's API contract, generated from the code (chapter 7).

contracts/openapi.json describes every route and every request and response shape. This module
writes it from the FastAPI app itself, never by hand, and `check` fails when the committed copy
no longer matches the code, saying what changed.

From python/:
    python -m helpdesk.contract write ../contracts/openapi.json
    python -m helpdesk.contract check ../contracts/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from helpdesk.main import build_app

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")


def document() -> dict[str, Any]:
    """The OpenAPI document for the helpdesk, from an app built on an empty in-memory database."""
    app = build_app(":memory:", with_sample_data=False)
    try:
        return app.openapi()
    finally:
        app.state.conn.close()


def render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _routes(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{method.upper()} {path}": operation
        for path, item in doc.get("paths", {}).items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def differences(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What changed between two versions of the contract, in words a reader can act on."""
    found: list[str] = []
    old_routes, new_routes = _routes(old), _routes(new)
    found += [f"route added: {r}" for r in new_routes if r not in old_routes]
    found += [f"route removed: {r}" for r in old_routes if r not in new_routes]
    found += [f"route changed: {r}" for r in new_routes if r in old_routes and new_routes[r] != old_routes[r]]
    old_schemas = old.get("components", {}).get("schemas", {})
    new_schemas = new.get("components", {}).get("schemas", {})
    found += [f"schema added: {s}" for s in new_schemas if s not in old_schemas]
    found += [f"schema removed: {s}" for s in old_schemas if s not in new_schemas]
    for name in new_schemas:
        if name not in old_schemas or new_schemas[name] == old_schemas[name]:
            continue
        old_fields = set(old_schemas[name].get("properties", {}))
        new_fields = set(new_schemas[name].get("properties", {}))
        added = [f"+{f}" for f in sorted(new_fields - old_fields)]
        removed = [f"-{f}" for f in sorted(old_fields - new_fields)]
        detail = f" (fields {', '.join(added + removed)})" if added or removed else ""
        found.append(f"schema changed: {name}{detail}")
    rest = {k for k in set(old) | set(new) if k not in ("paths", "components") and old.get(k) != new.get(k)}
    found += [f"changed: {k}" for k in sorted(rest)]
    return found or ["only the layout differs, not the content: regenerate the file to restore it"]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in ("write", "check"):
        print("Usage: python -m helpdesk.contract write|check <path-to-openapi.json>", file=sys.stderr)
        return 2
    command, path = args[0], Path(args[1])
    expected = render(document())
    if command == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8", newline="\n")
        print(f"Wrote {path}.")
        return 0

    regenerate = f"python -m helpdesk.contract write {args[1]}"
    if not path.exists():
        print(f"{path} doesn't exist. Create it with: {regenerate}", file=sys.stderr)
        return 1
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        print(f"{path} matches the code.")
        return 0
    try:
        changes = differences(json.loads(actual), json.loads(expected))
    except json.JSONDecodeError as err:
        changes = [f"the committed file isn't valid JSON ({err.msg}, line {err.lineno})"]
    print(f"{path} no longer matches the code:", file=sys.stderr)
    for change in changes:
        print(f"  {change}", file=sys.stderr)
    print(
        f"If the code is right, run {regenerate}, review the difference and commit it with the change. "
        "If the contract is right, change the code back. Never edit the contract by hand.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
