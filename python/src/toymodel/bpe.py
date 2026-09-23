"""A tiny byte-pair-encoding (BPE) tokenizer, trained on ten sentences.

Training starts from single letters and repeatedly merges the pair of neighbors that appears most
often. Words the training text used often end up as one token, and unfamiliar words are split
into pieces.
"""

from __future__ import annotations

import re
from collections import Counter

Pair = tuple[str, str]


def words_in(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _merge(word: tuple[str, ...], pair: Pair) -> tuple[str, ...]:
    out: list[str] = []
    i = 0
    while i < len(word):
        if i + 1 < len(word) and (word[i], word[i + 1]) == pair:
            out.append(word[i] + word[i + 1])
            i += 2
        else:
            out.append(word[i])
            i += 1
    return tuple(out)


def train(texts: list[str], num_merges: int) -> list[Pair]:
    """Learn up to num_merges merges. Ties break alphabetically, so training is repeatable."""
    words = Counter(tuple(w) for text in texts for w in words_in(text))
    merges: list[Pair] = []
    for _ in range(num_merges):
        pairs: Counter[Pair] = Counter()
        for word, freq in words.items():
            for pair in zip(word, word[1:], strict=False):
                pairs[pair] += freq
        if not pairs:
            break
        best = min(pairs, key=lambda p: (-pairs[p], p))
        if pairs[best] < 2:
            break  # a pair seen once is not a pattern
        merges.append(best)
        words = Counter({_merge(w, best): freq for w, freq in words.items()})
    return merges


def encode(text: str, merges: list[Pair]) -> list[list[str]]:
    """Split text into words, then each word into tokens by replaying the merges in order."""
    tokens = []
    for w in words_in(text):
        word = tuple(w)
        for pair in merges:
            word = _merge(word, pair)
        tokens.append(list(word))
    return tokens
