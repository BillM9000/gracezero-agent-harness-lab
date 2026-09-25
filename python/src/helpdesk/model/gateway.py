"""One front door for every call to a model provider (chapter 27).

A command asks the gateway for a client by team and route, never by key or provider, and only the
gateway builds a provider's client. Before each call it checks the team's month at the call's worst
case, and the team's share of the rate limits (requests and input tokens a minute), waiting when the
wait is short and refusing when it isn't. Then it routes: the cheapest model on the route first, at
the first of its deployments that isn't cooling down. A deployment that is overloaded, rate limited
or unreachable cools down, and the call goes to the model's next deployment, then to the next model.
A refusal goes to the next model on the route, never back to the one that refused. A route may also
answer an identical request from the same team from its cache, for a set time, with no call made.

Every attempt is a line in the record (calls.py): the team, the route, where it went and how it
ended, so cost is attributed as it's spent and a month's spend is read back from the same record.

The route is the whole of the choice. Which models may serve a job is decided by measuring them on it
(chapters 21 and 23), so a model that isn't on the route is never tried, however cheap or however
free. Everything here takes its data as arguments; python -m helpdesk.gateway builds the lab's
gateway from agents/policy.toml and the agent definitions, and runs a demo with made-up teams.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from helpdesk.model.budget import price, prompt_json, request_chars, request_json, response_chars
from helpdesk.model.calls import Call, CallLog, fingerprint, outcome_of, read
from helpdesk.model.types import Message, ModelClient, ModelResponse, ToolSpec, Unavailable

WINDOW = 60.0  # the rate limits are per minute, over the last 60 seconds


@dataclass(frozen=True)
class Team:
    """Who pays, and their share of the organization's limits (agents/policy.toml)."""

    name: str
    monthly_usd: float
    requests_per_minute: int
    input_tokens_per_minute: int


@dataclass(frozen=True)
class Route:
    """A job, and the models measured as good enough for it. cache_seconds 0 caches nothing."""

    name: str
    models: tuple[str, ...]
    cache_seconds: int = 0


@dataclass(frozen=True)
class Deployment:
    """One place a model can be reached: a provider, a region, an account."""

    name: str
    model: str


class Refused(RuntimeError):
    """The gateway refused the call before it was made."""

    outcome = ""


class RateLimited(Refused):
    outcome = "rate limited"

    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class OverBudget(Refused):
    outcome = "over the budget"


class NothingAnswered(RuntimeError):
    """Every deployment of every model on the route was down or cooling down."""


class Clock:
    """Real time. Tests and the demo pass one they move by hand."""

    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def money(usd: float) -> str:
    """Dollars, with enough places that a small sum isn't rounded to the next cent."""
    return f"${usd:,.2f}" if usd >= 1 else f"${usd:.4f}"


def month_of(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m")


def stamp(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat(timespec="seconds")


Connect = Callable[[Deployment, int], ModelClient]


class Gateway:
    def __init__(
        self,
        teams: Iterable[Team],
        routes: Iterable[Route],
        deployments: Iterable[Deployment],
        connect: Connect,
        log: CallLog,
        *,
        chars_per_token: float,
        clock: Clock | None = None,
        wait_up_to: float = 30.0,
        cool_for: float = 60.0,
    ) -> None:
        self.teams = {t.name: t for t in teams}
        self.routes = {r.name: r for r in routes}
        self.deployments: dict[str, list[Deployment]] = {}
        for d in deployments:
            self.deployments.setdefault(d.model, []).append(d)
        for route in self.routes.values():
            if not route.models:
                raise ValueError(f"route {route.name} has no models")
            for model in route.models:
                price(model, 0, 0)  # an unknown model fails here, before any call
                if model not in self.deployments:
                    raise ValueError(f"route {route.name}: {model} has no deployment to send it to")
        self.connect, self.log, self.chars_per_token = connect, log, chars_per_token
        self.clock = clock or Clock()
        self.wait_up_to, self.cool_for = wait_up_to, cool_for
        self.recent: dict[str, deque[list[float]]] = {}  # per team: [when, input tokens] a request
        self.cooling: dict[Deployment, float] = {}  # a deployment that failed, and until when
        self.cache: dict[str, tuple[float, str, ModelResponse]] = {}  # key: (expires, model, answer)
        self.clients: dict[tuple[Deployment, int], ModelClient] = {}
        # A month's spend is read back from the record itself, so a restart doesn't reset it.
        self.spent: dict[tuple[str, str], float] = {}
        if log.path.exists():
            for call in read(log.path):
                if call.team:
                    key = (call.team, call.at[:7])
                    self.spent[key] = self.spent.get(key, 0.0) + call.usd

    def client(self, team: str, route: str, max_tokens: int) -> ModelClient:
        if team not in self.teams:
            raise ValueError(
                f"{team!r} isn't a team the gateway knows. The teams are {', '.join(self.teams)}."
            )
        if route not in self.routes:
            raise ValueError(
                f"{route!r} isn't a route the gateway knows. The routes are {', '.join(self.routes)}."
            )
        return _Door(self, self.teams[team], self.routes[route], max_tokens)

    def month_spent(self, team: str) -> float:
        return self.spent.get((team, month_of(self.clock.time())), 0.0)

    # --- What the door does, in order.

    def order(self, route: Route, sent: float, max_tokens: int) -> list[str]:
        """The route's models, cheapest first for this request. A tie keeps the route's order."""
        return sorted(route.models, key=lambda model: price(model, sent, max_tokens))

    def check_budget(self, team: Team, worst: float) -> None:
        spent = self.month_spent(team.name)
        if spent + worst > team.monthly_usd:
            raise OverBudget(
                f"{team.name} has spent {money(spent)} this month, and this call could cost up to "
                f"{money(worst)}, past its {money(team.monthly_usd)} a month. Nothing was sent. "
                "Raising a team's budget is the platform team's call."
            )

    def admit(self, team: Team, tokens: float) -> list[float]:
        """Wait for room in the team's minute, or refuse. Returns the entry the call takes, so the
        estimate can be replaced by what the provider counted."""
        if tokens > team.input_tokens_per_minute:
            raise RateLimited(
                f"{team.name}: this request's {tokens:,.0f} input tokens are more than the team's "
                f"{team.input_tokens_per_minute:,} a minute, so it can never be sent. Send less history "
                "(chapter 10), or ask the platform team for a higher limit.",
                None,
            )
        window = self.recent.setdefault(team.name, deque())
        while True:
            now = self.clock.time()
            while window and window[0][0] <= now - WINDOW:
                window.popleft()
            if (
                len(window) < team.requests_per_minute
                and sum(t for _, t in window) + tokens <= team.input_tokens_per_minute
            ):
                entry = [now, tokens]
                window.append(entry)
                return entry
            wait = self.room_in(window, team, tokens, now)
            if wait > self.wait_up_to:
                raise RateLimited(
                    f"{team.name} is at its limit of {team.requests_per_minute} requests and "
                    f"{team.input_tokens_per_minute:,} input tokens a minute; there's room in {wait:.0f}s, "
                    f"longer than the {self.wait_up_to:.0f}s the gateway waits. Try again then.",
                    wait,
                )
            self.clock.sleep(wait)

    @staticmethod
    def room_in(window: deque[list[float]], team: Team, tokens: float, now: float) -> float:
        """Seconds until enough of the minute's requests age out for this one to fit."""
        count, used = len(window), sum(t for _, t in window)
        for when, spent in window:
            count, used = count - 1, used - spent
            if count < team.requests_per_minute and used + tokens <= team.input_tokens_per_minute:
                return max(0.0, when + WINDOW - now)
        return WINDOW

    def cache_key(self, team: Team, route: Route, max_tokens: int, request: str) -> str:
        """The whole request and the team: one team's answer is never another's, and a request that
        differs in any character, a tool result included, is a different request."""
        text = "\n".join((team.name, route.name, str(max_tokens), request))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def connected(self, deployment: Deployment, max_tokens: int) -> ModelClient:
        key = (deployment, max_tokens)
        if key not in self.clients:
            self.clients[key] = self.connect(deployment, max_tokens)
        return self.clients[key]


class _Door:
    def __init__(self, gateway: Gateway, team: Team, route: Route, max_tokens: int) -> None:
        self.gateway, self.team, self.route, self.max_tokens = gateway, team, route, max_tokens
        self.prompt = ""  # the fingerprint of the call being made, for its lines

    def write(
        self,
        outcome: str,
        model: str,
        deployment: str = "",
        *,
        error: str | None = None,
        response: ModelResponse | None = None,
        used: tuple[float, float, str] = (0.0, 0.0, "none"),
        ms: int = 0,
    ) -> None:
        """One line of the record. Refused, cached and failed calls cost nothing and say why."""
        g = self.gateway
        used_in, used_out, tokens_from = used
        g.log.write(
            Call(
                at=stamp(g.clock.time()),
                run=g.log.run,
                command=g.log.command,
                part="",
                model=model,
                outcome=outcome,
                stop_reason=response.stop_reason if response is not None else None,
                error=error,
                input_tokens=used_in,
                output_tokens=used_out,
                tokens_from=tokens_from,
                usd=price(model, used_in, used_out),
                ms=ms,
                prompt=self.prompt,
                team=self.team.name,
                route=self.route.name,
                deployment=deployment,
                request_id=response.request_id if response is not None else None,
            )
        )

    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse:
        g, team, route = self.gateway, self.team, self.route
        self.prompt = fingerprint(prompt_json(system, tools))
        sent = request_chars(system, messages, tools) / g.chars_per_token
        models = g.order(route, sent, self.max_tokens)

        # A cached answer costs nothing and takes nothing from the team's minute.
        key = None
        if route.cache_seconds:
            key = g.cache_key(team, route, self.max_tokens, request_json(system, messages, tools))
            hit = g.cache.get(key)
            if hit is not None and hit[0] > g.clock.time():
                self.write("cached", hit[1])
                return hit[2]

        try:
            # The month first, at the dearest model the route could try; then the team's minute.
            g.check_budget(team, max(price(m, sent, self.max_tokens) for m in models))
            entry = g.admit(team, sent)
        except Refused as refused:
            self.write(refused.outcome, models[0], error=type(refused).__name__)
            raise

        refusal: ModelResponse | None = None
        tried: list[str] = []
        for model in models:
            for deployment in g.deployments[model]:
                if g.cooling.get(deployment, 0.0) > g.clock.time():
                    tried.append(f"{model} at {deployment.name}, cooling down")
                    continue
                started = time.perf_counter()
                try:
                    response = g.connected(deployment, self.max_tokens).complete(
                        system=system, messages=messages, tools=tools
                    )
                except Unavailable as down:
                    # This deployment rests; the next one, or the next model, takes the call.
                    g.cooling[deployment] = g.clock.time() + (down.retry_after or g.cool_for)
                    self.write("unavailable", model, deployment.name, error=down.kind)
                    tried.append(f"{model} at {deployment.name}, {down.kind}")
                    continue
                except Exception as error:
                    self.write("error", model, deployment.name, error=type(error).__name__)
                    raise
                ms = round((time.perf_counter() - started) * 1000)
                if response.usage is not None:
                    used = (
                        float(response.usage.input_tokens),
                        float(response.usage.output_tokens),
                        "provider",
                    )
                else:
                    used = (sent, response_chars(response) / g.chars_per_token, "estimate")
                month = (team.name, month_of(g.clock.time()))
                g.spent[month] = g.spent.get(month, 0.0) + price(model, used[0], used[1])
                entry[1] = used[0]  # the minute counts what the provider counted, not the estimate
                outcome = outcome_of(response.stop_reason)
                self.write(outcome, model, deployment.name, response=response, used=used, ms=ms)
                if outcome == "refusal":
                    # The same model refuses again wherever it runs: try the next model on the route.
                    refusal = response
                    tried.append(f"{model} at {deployment.name}, refused")
                    break
                if key is not None and outcome == "ok":
                    g.cache[key] = (g.clock.time() + route.cache_seconds, model, response)
                return response
        if refusal is not None:
            return refusal  # every model on the route refused: the last refusal is the answer
        raise NothingAnswered(f"Nothing on route {route.name} answered: {'; '.join(tried)}.")
