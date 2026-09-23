"""Command line for the chapter 2 toys.

python -m toymodel tokens "reset my password" "rotate my passphrase"
python -m toymodel next "reset emails can take up to" --runs 5
python -m toymodel next "reset emails can take up to" --temperature 0
"""

from __future__ import annotations

import argparse

from toymodel import bpe, nextword
from toymodel.corpus import SUPPORT_REPLIES

MERGES = 100  # training stops early once no pair of neighbours repeats


def show_tokens(texts: list[str]) -> None:
    merges = bpe.train(SUPPORT_REPLIES, MERGES)
    for text in texts:
        words = bpe.encode(text, merges)
        count = sum(len(w) for w in words)
        print(f"{' '.join('|'.join(w) for w in words)}   ({len(words)} words, {count} tokens)")


def show_next(prompt: str, runs: int, temperature: float) -> None:
    table = nextword.train(SUPPORT_REPLIES)
    for seed in range(runs):
        print(f"{prompt} ... {nextword.continue_text(table, prompt, temperature=temperature, seed=seed)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m toymodel")
    sub = parser.add_subparsers(dest="command", required=True)
    tokens = sub.add_parser("tokens", help="split text into toy tokens")
    tokens.add_argument("text", nargs="+")
    nxt = sub.add_parser("next", help="continue a prompt, several times")
    nxt.add_argument("prompt")
    nxt.add_argument("--runs", type=int, default=5)
    nxt.add_argument("--temperature", type=float, default=1.0)
    args = parser.parse_args()
    if args.command == "tokens":
        show_tokens(args.text)
    else:
        show_next(args.prompt, args.runs, args.temperature)


if __name__ == "__main__":
    main()
