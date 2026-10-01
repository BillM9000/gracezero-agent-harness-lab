"""What a conversation costs when every call resends the whole history.

The Messages API is stateless: each call carries the system prompt and every earlier turn. So the
input grows with each turn, and so does its price. Run it:

python -m helpdesk.model.cost --model claude-opus-5-5 --system 2000 --user 300 --reply 500 --turns 10
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

# US dollars per million tokens (input, output), from Anthropic's models overview, read 2026-09-22.
# Prices change: check the pricing page before relying on them. Caching (chapter 27) lowers the
# price of resent input; it does not stop it being sent.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-6.1-sol": (2.0, 10.0),
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
# The day Anthropic's prices were read: gate.py records it with a promotion, and every model its
# definitions name is Anthropic's today. read_on gives the day for any model.
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


def call_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICES:
        raise ValueError(f"No price for {model!r}. Known models: {', '.join(sorted(PRICES))}.")
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def conversation(model: str, system: int, user: int, reply: int, turns: int) -> list[Turn]:
    """Each turn sends the system prompt, every earlier message and reply, and the new message."""
    result = []
    for n in range(1, turns + 1):
        sent = system + n * user + (n - 1) * reply
        result.append(Turn(n, sent, reply, call_cost(model, sent, reply)))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.model.cost")
    parser.add_argument("--model", default="claude-opus-5-5", choices=sorted(PRICES))
    parser.add_argument("--system", type=int, default=2000, help="system prompt tokens")
    parser.add_argument("--user", type=int, default=300, help="tokens per user message")
    parser.add_argument("--reply", type=int, default=500, help="tokens per model reply")
    parser.add_argument("--turns", type=int, default=10)
    args = parser.parse_args()

    turns = conversation(args.model, args.system, args.user, args.reply, args.turns)
    print(f"{'turn':>4}  {'input sent':>10}  {'output':>6}  {'cost (USD)':>10}")
    for t in turns:
        print(f"{t.number:>4}  {t.input_tokens:>10,}  {t.output_tokens:>6,}  {t.cost:>10.4f}")
    total = sum(t.cost for t in turns)
    ratio = turns[-1].cost / turns[0].cost
    print(f"Total: ${total:.4f} for {args.turns} turns. The last turn cost {ratio:.1f} times the first.")


if __name__ == "__main__":
    main()
