"""A spending cap for commands that make many model calls (chapter 23).

A golden set's calls multiply: cases times trials times the requests each run makes, and a judge's
criteria times replies times trials. A Budget wraps every model client one command builds and keeps
one count for all of them. Before each call it works out what the call could cost at worst, the
request's input plus max_tokens of output, and refuses the call if that could take the total past
the cap. After the call it adds what the provider says was used, or, from the mock, an estimate.

So a capped run stops before the call that could cross the cap, not after it. The input side is an
estimate (characters over chars_per_token), so the cap can be passed by at most that estimate's
error on one call.

Given a CallLog (chapter 26), the budget also records every call it sees, refusals, cut-off answers,
errors and calls the cap refused included: see calls.py.
"""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from helpdesk.model.anthropic_client import to_api, tool_to_api
from helpdesk.model.calls import Call, CallLog, fingerprint, now, outcome_of
from helpdesk.model.cost import PRICES
from helpdesk.model.types import Message, ModelClient, ModelResponse, ToolSpec


class BudgetReached(RuntimeError):
    """The next call could take the total past the cap, so it wasn't made."""


@dataclass
class Spend:
    calls: int = 0
    input_tokens: float = 0.0
    output_tokens: float = 0.0
    usd: float = 0.0


def plain(value: Any) -> Any:
    """A provider's own object as data json can write. A real client keeps the model's turn as the
    SDK's response objects (raw), pydantic models, and sends them back on the next call, so the
    request a tool run's second call measures holds them: a pydantic model gives its JSON dump, a
    dataclass its fields, and anything else its text."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return str(value)


def as_json(value: Any) -> str:
    """Plain data as json.dumps writes it, and a provider's objects as their plain data."""
    return json.dumps(value, ensure_ascii=False, default=plain)


def request_json(system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> str:
    """One request as the Anthropic adapter would send it."""
    request = {
        "system": system,
        "tools": [tool_to_api(t) for t in tools],
        "messages": [to_api(m) for m in messages],
    }
    return as_json(request)


def request_chars(system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> int:
    """Characters of one request (the same measure as helpdesk.patterns.request_size, which a test
    keeps equal)."""
    return len(request_json(system, messages, tools))


def response_chars(response: ModelResponse) -> int:
    """Characters of what the model wrote: its text and its tool calls."""
    calls = [{"name": c.name, "input": c.arguments} for c in response.tool_calls]
    return len(response.text) + (len(as_json(calls)) if calls else 0)


def price(model: str, input_tokens: float, output_tokens: float) -> float:
    if model not in PRICES:
        raise ValueError(f"No price for {model!r}. Known models: {', '.join(sorted(PRICES))}.")
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


class Budget:
    """One count, and one cap, for every model client a command builds. cap_usd None counts
    without a cap, which is how the gate measures what a run would cost."""

    def __init__(self, cap_usd: float | None, chars_per_token: float, log: CallLog | None = None) -> None:
        if cap_usd is not None and cap_usd <= 0:
            raise ValueError("a cap must be more than $0")
        self.cap = cap_usd
        self.chars_per_token = chars_per_token
        self.spent = Spend()
        self.worst_call = 0.0  # the most any one call so far could have cost
        self.log = log
        self.part = ""  # what the command is running now, for the record: a suite, the judge

    def wrap(self, inner: ModelClient, model: str, max_tokens: int) -> ModelClient:
        price(model, 0, 0)  # an unknown model fails here, before any call
        capped = _Capped(self, inner, model, max_tokens)
        return capped if self.log is None else _Recorded(self, capped, self.log)

    def check(self, worst: float) -> None:
        self.worst_call = max(self.worst_call, worst)
        if self.cap is not None and self.spent.usd + worst > self.cap:
            raise BudgetReached(
                f"stopped before call {self.spent.calls + 1}: ${self.spent.usd:.2f} spent, and the next call "
                f"could cost up to ${worst:.2f}, past the ${self.cap:.2f} cap. Nothing after it ran."
            )

    def add(self, model: str, input_tokens: float, output_tokens: float) -> None:
        self.spent.calls += 1
        self.spent.input_tokens += input_tokens
        self.spent.output_tokens += output_tokens
        self.spent.usd += price(model, input_tokens, output_tokens)


class _Capped:
    def __init__(self, budget: Budget, inner: ModelClient, model: str, max_tokens: int) -> None:
        self.budget, self.inner, self.model, self.max_tokens = budget, inner, model, max_tokens

    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse:
        sent = request_chars(system, messages, tools) / self.budget.chars_per_token
        # The cap is checked before the call: the worst it could cost is its input and max_tokens.
        self.budget.check(price(self.model, sent, self.max_tokens))
        response = self.inner.complete(system=system, messages=messages, tools=tools)
        if response.usage is not None:
            used_in, used_out = float(response.usage.input_tokens), float(response.usage.output_tokens)
        else:
            used_in, used_out = sent, response_chars(response) / self.budget.chars_per_token
        self.budget.add(self.model, used_in, used_out)
        self.last = (used_in, used_out, response.usage is not None)
        return response


class _Recorded:
    """Writes one line for every call through the cap, however it ended, and passes on what the
    call returned or raised."""

    def __init__(self, budget: Budget, capped: _Capped, log: CallLog) -> None:
        self.budget, self.capped, self.log = budget, capped, log

    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse:
        request = request_json(system, messages, tools)
        at, started = now(), time.perf_counter()

        def write(outcome: str, stop: str | None, error: str | None, used: tuple[float, float, bool]) -> None:
            used_in, used_out, reported = used
            self.log.write(
                Call(
                    at=at,
                    run=self.log.run,
                    command=self.log.command,
                    part=self.budget.part,
                    model=self.capped.model,
                    outcome=outcome,
                    stop_reason=stop,
                    error=error,
                    input_tokens=used_in,
                    output_tokens=used_out,
                    tokens_from="provider" if reported else "estimate" if stop else "none",
                    usd=price(self.capped.model, used_in, used_out),
                    ms=round((time.perf_counter() - started) * 1000),
                    request=fingerprint(request),
                )
            )

        try:
            response = self.capped.complete(system=system, messages=messages, tools=tools)
        except BudgetReached:
            # Refused before it was made: nothing was sent, and nothing was spent.
            write("over the cap", None, None, (0.0, 0.0, False))
            raise
        except Exception as error:
            # No usage came back, so the budget counted nothing; the record says what went wrong.
            write("error", None, type(error).__name__, (0.0, 0.0, False))
            raise
        write(outcome_of(response.stop_reason), response.stop_reason, None, self.capped.last)
        return response
