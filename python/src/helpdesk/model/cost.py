"""What a conversation costs when every call resends the whole history.

The Messages API is stateless: each call carries the system prompt and every earlier turn. So the
input grows with each turn, and so does its price. Run it:

python -m helpdesk.model.cost --model claude-opus-5-5 --system 2000 --user 300 --reply 500 --turns 10

Two levers lower that (chapter 27). --cache prices the same turns with prompt caching, each turn
reading what the one before sent from the cache and writing the rest. --keep N sends only the last N
exchanges of the history. Caching changes what the input costs; trimming changes what is sent.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

# US dollars per million tokens (input, output), from each provider's pricing page, read on the day
# PROVIDERS gives: Anthropic's models overview on 2026-09-22, checked against its pricing page on
# 2026-09-25, and OpenAI's pricing page on 2026-10-01 (its standard tier's short-context rates).
# Prices change: read the page again before relying on them, and change them here (agents/policy.toml's
# output prices must match; a test checks). Caching (chapter 27) lowers the price of resent input; it
# does not stop it being sent.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-6.1-sol": (2.0, 10.0),
}

# Prompt caching (chapter 27), from each provider's prompt caching page on the day PROVIDERS gives.
# Anthropic: writing to the 5-minute cache costs 1.25 times the base input price, and reading from it
# what CACHE_READ says; its page gives the shortest prompt each model caches. OpenAI, for GPT-5.6 and
# later: writes cost 1.25 times the uncached input rate, reads 0.1 times on most models and 0.05 on
# GPT-6.1 Sol, the shortest cacheable prompt is 1,024 tokens, and a prefix stays usable for 30 minutes
# after its last use. A shorter prompt is sent uncached, and no error says so. A test keeps these
# covering exactly the models in PRICES.
CACHE_WRITE = 1.25
CACHE_READ = {
    "claude-fable-5-1": 0.025,
    "claude-opus-5-5": 0.05,
    "claude-sonnet-5": 0.1,
    "claude-haiku-4-5-20251001": 0.1,
    "gpt-6.1-sol": 0.05,
}
CACHE_MIN_TOKENS = {
    "claude-fable-5-1": 512,
    "claude-opus-5-5": 512,
    "claude-sonnet-5": 1024,
    "claude-haiku-4-5-20251001": 4096,
    "gpt-6.1-sol": 1024,
}

# Where each model's prices came from, and when. A model's provider is the one whose pages list it;
# a test keeps every model in PRICES under exactly one provider, and another keeps each approved
# model's provider here equal to its section in agents/models.toml.
PROVIDERS = {
    "Anthropic": {
        "pricing": "https://platform.claude.com/docs/en/about-claude/pricing",
        "caching": "https://platform.claude.com/docs/en/build-with-claude/prompt-caching",
        "read": "2026-09-25",
        "models": ("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"),
    },
    "OpenAI": {
        "pricing": "https://developers.openai.com/api/docs/pricing",
        "caching": "https://developers.openai.com/api/docs/guides/prompt-caching",
        "read": "2026-10-01",
        "models": ("gpt-6.1-sol",),
    },
}
# The day Anthropic's prices were read: gate.py records it with a promotion, and the two models a
# promotion is measured with, the triage assistant's and the first judge's (agents/triage.toml and
# agents/judge.toml), are Anthropic's today. read_on gives the day for any model.
PRICES_SOURCE = PROVIDERS["Anthropic"]["pricing"]
PRICES_READ = PROVIDERS["Anthropic"]["read"]


def provider_of(model: str) -> str:
    """The provider whose pages the model's prices came from."""
    for name, provider in PROVIDERS.items():
        if model in provider["models"]:
            return name
    raise ValueError(f"No provider lists {model!r} in PROVIDERS. Known models: {', '.join(sorted(PRICES))}.")


def read_on(model: str) -> str:
    """The day the model's prices were read from its provider's page."""
    return PROVIDERS[provider_of(model)]["read"]


@dataclass(frozen=True)
class Turn:
    number: int
    input_tokens: int
    output_tokens: int
    cost: float
    cache_read: int = 0  # of input_tokens, read from the cache
    cache_written: int = 0  # of input_tokens, written to it


def call_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICES:
        raise ValueError(f"No price for {model!r}. Known models: {', '.join(sorted(PRICES))}.")
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def cached_cost(model: str, read: int, written: int, uncached: int, output_tokens: int) -> float:
    price_in, _ = PRICES[model]
    cache = (read * CACHE_READ[model] + written * CACHE_WRITE) * price_in / 1_000_000
    return cache + call_cost(model, uncached, output_tokens)


def conversation(
    model: str,
    system: int,
    user: int,
    reply: int,
    turns: int,
    *,
    cache: bool = False,
    keep: int | None = None,
) -> list[Turn]:
    """Each turn sends the system prompt, the earlier messages and replies it keeps, and the new
    message. With cache, the whole request is written to the cache and the next turn reads what this
    one sent, as automatic caching does within its 5 minutes; a request shorter than the model's
    minimum isn't cached at all. Trimming changes the start of every request, so a cache written for
    the last one would miss: the two are priced apart."""
    if cache and keep is not None:
        raise ValueError("Price caching or trimming, not both: trimming changes what the cache would match.")
    if keep is not None and keep < 0:
        raise ValueError("--keep is how many earlier exchanges to send, 0 or more.")
    result, before = [], 0
    for n in range(1, turns + 1):
        kept = n - 1 if keep is None else min(n - 1, keep)
        sent = system + kept * (user + reply) + user
        if cache and model in PRICES and sent >= CACHE_MIN_TOKENS[model]:
            read = before  # the last request, whole, is the start of this one
            result.append(
                Turn(n, sent, reply, cached_cost(model, read, sent - read, 0, reply), read, sent - read)
            )
            before = sent
        else:
            result.append(Turn(n, sent, reply, call_cost(model, sent, reply)))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.model.cost")
    parser.add_argument("--model", default="claude-opus-5-5", choices=sorted(PRICES))
    parser.add_argument("--system", type=int, default=2000, help="system prompt tokens")
    parser.add_argument("--user", type=int, default=300, help="tokens per user message")
    parser.add_argument("--reply", type=int, default=500, help="tokens per model reply")
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--cache", action="store_true", help="price with prompt caching (chapter 27)")
    parser.add_argument("--keep", type=int, help="send only the last N exchanges (chapter 27)")
    args = parser.parse_args()

    try:
        turns = conversation(
            args.model, args.system, args.user, args.reply, args.turns, cache=args.cache, keep=args.keep
        )
    except ValueError as error:
        parser.error(str(error))
    if args.cache:
        heads = (
            ("turn", 4),
            ("input sent", 10),
            ("cache read", 10),
            ("written", 7),
            ("output", 6),
            ("cost (USD)", 10),
        )
        print("  ".join(f"{name:>{width}}" for name, width in heads))
        for t in turns:
            print(
                f"{t.number:>4}  {t.input_tokens:>10,}  {t.cache_read:>10,}  {t.cache_written:>7,}  "
                f"{t.output_tokens:>6,}  {t.cost:>10.4f}"
            )
    else:
        print(f"{'turn':>4}  {'input sent':>10}  {'output':>6}  {'cost (USD)':>10}")
        for t in turns:
            print(f"{t.number:>4}  {t.input_tokens:>10,}  {t.output_tokens:>6,}  {t.cost:>10.4f}")
    total = sum(t.cost for t in turns)
    ratio = turns[-1].cost / turns[0].cost
    print(f"Total: ${total:.4f} for {args.turns} turns. The last turn cost {ratio:.1f} times the first.")
    if args.cache:
        read = CACHE_READ[args.model]
        print(
            f"Cache prices read {read_on(args.model)} from {provider_of(args.model)}'s page: writes "
            f"{CACHE_WRITE}x and reads {read}x the input price."
        )


if __name__ == "__main__":
    main()
