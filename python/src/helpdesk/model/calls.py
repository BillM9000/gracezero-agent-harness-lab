"""A record of every model call a command makes (chapter 26).

A cap (budget.py) decides whether a call may be made; this file remembers what each call was. One
JSON line a call, appended as it happens: when, which command and part of it, which model, how it
ended, the tokens and what they cost, how long it took, and a fingerprint of the request.

How a call ended is the part people leave out. A refusal and an answer cut off at max_tokens both
arrive as successful responses, so a count of errors never sees them; here each is its own outcome,
beside errors the client raised and calls the cap refused before they were made.

The record keeps a fingerprint of the request, not the request: what the assistant sends includes
what customers wrote, and an audit trail that copies it becomes one more place that data lives. The
fingerprint proves which request a line describes, for anyone who still has the request.

python -m helpdesk.gate run --record FILE writes a record; python -m helpdesk.calls FILE sums it up.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path

# How a call ended. Everything but "ok" is a failure a dashboard should count.
OUTCOMES = ("ok", "refusal", "cut off", "error", "over the cap")


def outcome_of(stop_reason: str) -> str:
    """A refusal and a cut-off answer come back as successful responses (chapter 2)."""
    if stop_reason == "refusal":
        return "refusal"
    if stop_reason in ("max_tokens", "model_context_window_exceeded"):
        return "cut off"
    return "ok"


def fingerprint(request: str) -> str:
    """The first 16 hex digits of the request's SHA-256: enough to match a line to a request."""
    return hashlib.sha256(request.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Call:
    at: str  # when the call started, UTC
    run: str  # one id for every call one command made
    command: str
    part: str
    model: str
    outcome: str
    stop_reason: str | None
    error: str | None  # the exception's type, for an error
    input_tokens: float  # the provider's count, or an estimate from characters
    output_tokens: float
    tokens_from: str  # "provider", "estimate", or "none" for a call that never came back
    usd: float
    ms: int
    request: str  # fingerprint(), never the request itself


class CallLog:
    """Appends one line a call to path. Every call one command makes shares its run id."""

    def __init__(self, path: Path, command: str) -> None:
        self.path, self.command = path, command
        self.run = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{os.getpid()}"
        self.written = 0
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, call: Call) -> None:
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(asdict(call), ensure_ascii=False) + "\n")
        self.written += 1


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


NAMES = [f.name for f in fields(Call)]


def read(path: Path) -> list[Call]:
    """Every line of a record. A line that isn't a call is refused with its number, rather than
    skipped: a summary of part of a record would look like a summary of all of it."""
    calls = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            found = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: not JSON ({error.msg}).") from None
        if not isinstance(found, dict) or sorted(found) != sorted(NAMES):
            raise ValueError(f"{path}:{number}: not a call record; a line has exactly {', '.join(NAMES)}.")
        if found["outcome"] not in OUTCOMES:
            raise ValueError(f"{path}:{number}: unknown outcome {found['outcome']!r}.")
        calls.append(Call(**found))
    return calls


def table(rows: Sequence[Sequence[str]], right: Sequence[bool]) -> list[str]:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for row in rows:
        cells = zip(row, widths, right, strict=True)
        lines.append("  ".join(cell.rjust(w) if r else cell.ljust(w) for cell, w, r in cells).rstrip())
    return lines


def summary(calls: Iterable[Call], chars_per_token: float) -> list[str]:
    calls = list(calls)
    if not calls:
        return ["No calls recorded."]
    groups: dict[tuple[str, str], list[Call]] = {}
    for call in calls:
        groups.setdefault((call.part or "-", call.model), []).append(call)
    rows = [("part", "model", "calls", "input tokens", "output tokens", "cost", "failed")]
    for (part, model), group in groups.items():
        rows.append(
            (
                part,
                model,
                f"{len(group):,}",
                f"{round(sum(c.input_tokens for c in group)):,}",
                f"{round(sum(c.output_tokens for c in group)):,}",
                f"${sum(c.usd for c in group):.2f}",
                f"{sum(c.outcome != 'ok' for c in group):,}",
            )
        )
    runs = {c.run for c in calls}
    commands = sorted({c.command for c in calls})
    lines = [
        f"{len(calls):,} calls from {len(runs)} run{'' if len(runs) == 1 else 's'} of {', '.join(commands)}.",
        "",
        *table(rows, (False, False, True, True, True, True, True)),
        "",
    ]
    estimated = sum(c.tokens_from == "estimate" for c in calls)
    reported = sum(c.tokens_from == "provider" for c in calls)
    if estimated and not reported:
        lines.append(f"Tokens: estimated at {chars_per_token} characters a token; the mock reports none.")
    elif estimated:
        lines.append(
            f"Tokens: the provider's counts for {reported:,} calls, estimated at {chars_per_token} "
            f"characters a token for {estimated:,}."
        )
    else:
        lines.append("Tokens: the provider's own counts.")
    failed = [c for c in calls if c.outcome != "ok"]
    if not failed:
        lines.append("Failed: none (no refusals, cut-off answers, errors or calls over the cap).")
    else:
        kinds: dict[str, int] = {}
        for c in failed:
            name = f"{c.outcome} ({c.error})" if c.error else c.outcome
            kinds[name] = kinds.get(name, 0) + 1
        lines.append("Failed: " + ", ".join(f"{n} {kind}" for kind, n in sorted(kinds.items())) + ".")
    return lines
