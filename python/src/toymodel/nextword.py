"""A tiny next-word model: count which word follows each pair of words, then sample.

It shows two things real models share. Sampled output varies from run to run. And the most likely
continuation is whatever was most common in the training text, whether or not it is true.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from toymodel.bpe import words_in

END = "<end>"
Context = tuple[str, str]


def train(sentences: list[str]) -> dict[Context, Counter[str]]:
    """Count, for every pair of consecutive words, which word came next."""
    table: dict[Context, Counter[str]] = defaultdict(Counter)
    for sentence in sentences:
        words = [*words_in(sentence), END]
        for a, b, nxt in zip(words, words[1:], words[2:], strict=False):
            table[(a, b)][nxt] += 1
    return dict(table)


def next_word(counts: Counter[str], temperature: float, rng: random.Random) -> str:
    """Temperature 0 always takes the most common word. Higher temperatures flatten the odds."""
    if temperature == 0:
        return min(counts, key=lambda w: (-counts[w], w))
    choices = sorted(counts)
    weights = [counts[w] ** (1 / temperature) for w in choices]
    return rng.choices(choices, weights=weights)[0]


def continue_text(
    table: dict[Context, Counter[str]],
    prompt: str,
    *,
    max_words: int = 6,
    temperature: float = 1.0,
    seed: int = 0,
) -> str:
    rng = random.Random(seed)
    words = words_in(prompt)
    added: list[str] = []
    while len(added) < max_words:
        counts = table.get((words[-2], words[-1]))
        if not counts:
            break  # the model has never seen these two words together
        word = next_word(counts, temperature, rng)
        if word == END:
            break
        words.append(word)
        added.append(word)
    return " ".join(added)
