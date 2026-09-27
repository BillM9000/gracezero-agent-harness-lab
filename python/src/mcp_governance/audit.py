"""The audit log (chapter 13): who called which tool, for whom, with what result.

One JSON object a line, appended for every request to the MCP endpoint, refused or not:

    time      when the server answered, in UTC
    client    the application that called: the verified token's client_id, or "-" with no valid token
    subject   the person the token names, as the issuer identifies them, or "-"
    person    that person as the server knows them, or "-"
    method    the JSON-RPC method, such as tools/call
    name      the tool or prompt, or the resource's URI; "-" for methods without one
    arguments the tool's or prompt's arguments, as sent
    status    the HTTP status of the answer
    outcome   what happened: ok, a tool error, a protocol error, or refused and why
    token     the token's id (jti), so a record can be tied to a token without keeping the token

The token itself is never written. python -m mcp_governance audit prints the log as a table.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

UNKNOWN = "-"


class AuditLog:
    """An append-only file of records. Opened when the server starts, so a server that can't keep a
    record refuses to start instead of serving without one."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file: TextIO = path.open("a", encoding="utf-8")

    def record(self, **fields: Any) -> dict[str, Any]:
        entry = {"time": datetime.now(UTC).isoformat(timespec="seconds"), **fields}
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()
        return entry

    def close(self) -> None:
        self._file.close()


def read(path: Path) -> list[dict[str, Any]]:
    """Every record in the log, oldest first. A log that doesn't exist yet has none. Records are
    split at "\\n" alone: record writes arguments as they were sent, so U+2028, U+0085 and the
    other characters str.splitlines() also breaks at can be inside one."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def table(records: list[dict[str, Any]]) -> list[str]:
    """The records as lines to scan: when, who called, for whom, which request, and what came of it."""
    rows = [("time", "client", "for", "request", "outcome")]
    for r in records:
        request = r.get("method", UNKNOWN)
        if r.get("name", UNKNOWN) != UNKNOWN:
            request += f" {r['name']}"
        if r.get("arguments"):
            request += f" {json.dumps(r['arguments'])}"
        rows.append(
            (r["time"][11:19], r.get("client", UNKNOWN), r.get("person", UNKNOWN), request, r["outcome"])
        )
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    return [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:4])) + "  " + row[4] for row in rows
    ]
