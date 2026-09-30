"""The audit log (chapter 13): who called which tool, for whom, with what result.

One JSON object a line, appended for every request to the MCP endpoint, refused or not:

    time      when the record was written, in UTC: for an outcome, when the server answered
    request   an id for the request, the same on its attempt and its outcome
    client    the application that called: the verified token's client_id, or "-" with no valid token
    subject   the person the token names, as the issuer identifies them, or "-"
    person    that person as the server knows them, or "-"
    method    the JSON-RPC method, such as tools/call
    name      the tool or prompt, or the resource's URI; "-" for methods without one
    arguments the tool's or prompt's arguments, as sent
    status    the HTTP status of the answer; null on an attempt
    outcome   what happened: ok, a tool error, a protocol error, failed and why, or refused and why
    token     the token's id (jti), so a record can be tied to a token without keeping the token

A request the front door refuses gets one record, written before the refusal is sent. One it passes to
the MCP server gets two: the attempt, written before the server acts on it, with the outcome "passed to
the server", then the outcome, written when the server has answered or has failed. So a request whose
handling raises an error, or that a server stopped in the middle of, still leaves a record of who asked
for what. The token itself is never written. python -m mcp_governance audit prints the log as a table.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

UNKNOWN = "-"
# The outcome on an attempt's record, and what read() reports when no outcome followed it.
ATTEMPT = "passed to the server"
NO_OUTCOME = "passed to the server, and no outcome was recorded"


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


def records(path: Path) -> list[dict[str, Any]]:
    """Every record in the log as it was written, oldest first. A log that doesn't exist yet has none.
    Records are split at "\\n" alone: record writes arguments as they were sent, so U+2028, U+0085 and
    the other characters str.splitlines() also breaks at can be inside one."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def read(path: Path) -> list[dict[str, Any]]:
    """Every request in the log, in the order they came, one record each: its outcome, in the place of
    its attempt, or the attempt with the outcome NO_OUTCOME when none was written."""
    requests: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for r in records(path):
        key = r.get("request")
        if key is not None and key in by_id:
            by_id[key].clear()
            by_id[key].update(r)
            continue
        entry = {**r, "outcome": NO_OUTCOME} if r.get("outcome") == ATTEMPT else dict(r)
        requests.append(entry)
        if key is not None:
            by_id[key] = entry
    return requests


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
