"""Retrieval over the knowledge base (chapter 9): passages, two rankers, and rank fusion.

Articles are split into passages ("chunks") at their own "## " headings, and every passage carries
its article's title and heading, so it still makes sense on its own. Two rankers score passages
against a question:

- BM25, keyword search. It scores the passages that share the question's words, weighting rare
  words above common ones and short passages above long ones, with the formula in Robertson and
  Zaragoza's survey of BM25 (2009). It matches whole words exactly.
- A vector stand-in. Each text becomes a list of 512 numbers, and passages are ranked by how
  closely their list points the same way as the question's (cosine similarity). Real embeddings
  come from an embedding model, which places texts with similar meanings close together. THIS IS
  NOT ONE: it counts each word's three-letter pieces into 512 slots, so it captures spelling, not
  meaning. It is deterministic and free, which is why the lab uses it. It can match "pasword" to
  "password", or "invoices" to "invoice"; it can never match "sign in" to "log in".

Hybrid search fuses the two rankings with reciprocal rank fusion (Cormack, Clarke and Buettcher,
SIGIR 2009): each ranking gives a passage 1 / (60 + its rank), and the sums set the order. A passage
must clear a floor in at least one ranker to be returned at all, so a question the knowledge base
can't answer gets nothing back, not the three least-bad passages.
"""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

Method = Literal["hybrid", "bm25", "vector"]
METHODS: tuple[Method, ...] = ("hybrid", "bm25", "vector")
Split = Literal["section", "article", "sentence"]
SPLITS: tuple[Split, ...] = ("section", "article", "sentence")

# Words too common to say anything about a passage. Negations such as "not" and "can't" are kept
# out of this list on purpose: citations.py needs them to count.
STOP_WORDS = frozenset(
    """a about after all also am an and any are as at be been before but by can could did do does
    doing each for from get got had has have how i i'm if in into is it it's its just me my of on
    once or our ours out over please so some such than that the their them then there these they
    this those through to too up us very was we were what when where which while who whom why will
    with would you you're your yours""".split()
)
WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def words(text: str) -> list[str]:
    """The words both rankers read: lowercase, without stop words or stray single letters."""
    found = WORD.findall(text.lower().replace(chr(0x2019), "'"))  # U+2019, the curly apostrophe phones type
    return [w for w in found if w not in STOP_WORDS and (len(w) > 1 or w.isdigit())]


# --- Passages ---------------------------------------------------------------------------------

MAX_WORDS = 120


@dataclass(frozen=True)
class Chunk:
    id: str  # "<article>#<n>", the id an answer cites: 1#2 is article 1's second passage
    article_id: int
    title: str
    heading: str
    text: str

    @property
    def indexed(self) -> str:
        """What the rankers read, and what the assistant is shown: the passage, with its article's
        title and heading in front, so a passage that says only "It expires after 7 days" still
        says what expires."""
        return f"{self.title} > {self.heading}: {self.text}" if self.heading else f"{self.title}: {self.text}"


def sections(body: str) -> list[tuple[str, list[str]]]:
    """An article body as (heading, paragraphs) pairs; text before the first heading has none."""
    found: list[tuple[str, list[str]]] = [("", [])]
    paragraph: list[str] = []

    def end_paragraph() -> None:
        if paragraph:
            found[-1][1].append(" ".join(paragraph))
            paragraph.clear()

    for line in body.splitlines():
        if line.startswith("## "):
            end_paragraph()
            found.append((line[3:].strip(), []))
        elif line.strip():
            paragraph.append(line.strip())
        else:
            end_paragraph()
    end_paragraph()
    return [(heading, paragraphs) for heading, paragraphs in found if paragraphs]


def pieces(paragraphs: Sequence[str], max_words: int) -> list[str]:
    """Pack paragraphs into pieces of at most max_words, splitting a long paragraph at sentence
    ends. One sentence longer than max_words stays whole: cutting mid-sentence loses its meaning."""
    units: list[str] = []
    for paragraph in paragraphs:
        units += [paragraph] if len(paragraph.split()) <= max_words else SENTENCE_END.split(paragraph)
    packed: list[str] = []
    current: list[str] = []
    for unit in units:
        if current and len(" ".join([*current, unit]).split()) > max_words:
            packed.append(" ".join(current))
            current = []
        current.append(unit)
    if current:
        packed.append(" ".join(current))
    return packed


def chunk_article(
    article_id: int, title: str, body: str, *, split: Split = "section", max_words: int = MAX_WORDS
) -> list[Chunk]:
    """Split one article into passages. "section" (the default) splits at the article's own
    headings; "article" keeps the whole article as one passage; "sentence" makes every sentence
    its own passage. Ids count from 1 within each article."""
    parts: list[tuple[str, str]] = []
    if split == "article":
        text = " ".join(" ".join([heading, *paragraphs]) for heading, paragraphs in sections(body))
        parts = [("", text.strip())]
    else:
        for heading, paragraphs in sections(body):
            chosen = pieces(paragraphs, max_words) if split == "section" else pieces(paragraphs, 0)
            parts += [(heading, piece) for piece in chosen]
    return [
        Chunk(f"{article_id}#{n}", article_id, title, heading, text)
        for n, (heading, text) in enumerate(parts, 1)
    ]


# --- Ranker 1: BM25 ---------------------------------------------------------------------------

# Robertson and Zaragoza (2009) report that values such as 1.2 < k1 < 2 and 0.5 < b < 0.8 are
# reasonably good in many circumstances. k1 sets how fast repeats of a word stop adding to a
# passage's score; b sets how much a long passage is marked down.
K1 = 1.5
B = 0.75


class BM25:
    def __init__(self, passages: Sequence[list[str]]) -> None:
        self.counts = [Counter(p) for p in passages]
        self.lengths = [len(p) for p in passages]
        self.average_length = sum(self.lengths) / len(passages) if passages else 0.0
        n = len(passages)
        containing = Counter(word for counts in self.counts for word in counts)
        # The survey's IDF, log((N - n + 0.5) / (n + 0.5)), goes below zero for a word in more
        # than half the passages. Such a word gets no weight here, rather than a negative one.
        self.idf = {w: max(0.0, math.log((n - c + 0.5) / (c + 0.5))) for w, c in containing.items()}

    def scores(self, question: list[str]) -> list[float]:
        """One score per passage: the sum, over the question's words, of each word's weight."""
        found = []
        for counts, length in zip(self.counts, self.lengths, strict=True):
            norm = K1 * (1 - B + B * length / self.average_length)
            found.append(sum(self.idf[w] * counts[w] / (norm + counts[w]) for w in question if w in counts))
        return found


# --- Ranker 2: the vector stand-in ------------------------------------------------------------

DIMENSIONS = 512


def trigram_vector(text: str) -> list[float]:
    """A fixed-length vector for a text: NOT an embedding from a model (see the module docstring).
    Each word, marked at both ends, is cut into three-letter pieces ("#pa", "pas", "ass", ...), and
    each piece adds 1 to one of 512 slots, chosen by a stable hash. The vector is then scaled to
    length 1, so the dot product of two vectors is their cosine similarity."""
    vector = [0.0] * DIMENSIONS
    for word in words(text):
        marked = f"#{word}#"
        for i in range(len(marked) - 2):
            vector[zlib.crc32(marked[i : i + 3].encode()) % DIMENSIONS] += 1.0
    length = math.sqrt(sum(v * v for v in vector))
    return [v / length for v in vector] if length else vector


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    # Both vectors have length 1, so the dot product is the cosine of the angle between them.
    return sum(x * y for x, y in zip(a, b, strict=True))


# --- Fusion -----------------------------------------------------------------------------------

# Cormack, Clarke and Buettcher fixed k = 60 in a pilot and kept it. The constant stops one ranker's
# first place from outweighing a passage both rankers put near the top.
RRF_K = 60


def reciprocal_rank_fusion(rankings: Mapping[str, Sequence[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Fuse rankings of the same items, best first in each, into one: sum 1 / (k + rank)."""
    scores: dict[int, float] = {}
    for ranking in rankings.values():
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


# --- The index --------------------------------------------------------------------------------

# A passage is returned only if it clears a floor in at least one ranker: BM25 above zero (it
# shares a word with the question), or a cosine similarity of at least VECTOR_FLOOR. The floor was
# set by looking at the golden set's questions, evals/kb_questions.json, which makes that set a
# check on the floor, not proof of it: a question worded differently can fall either side.
VECTOR_FLOOR = 0.3


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    ranks: dict[str, int]  # the passage's place in each ranker that returned it; 1 is the top


class Index:
    def __init__(self, chunks: Iterable[Chunk]) -> None:
        self.chunks = list(chunks)
        self.bm25 = BM25([words(c.indexed) for c in self.chunks])
        self.vectors = [trigram_vector(c.indexed) for c in self.chunks]

    @classmethod
    def build(
        cls, articles: Iterable[Mapping[str, Any]], *, split: Split = "section", max_words: int = MAX_WORDS
    ) -> Index:
        """An index over articles, each a mapping with id, title and body (a kb_articles row)."""
        return cls(
            chunk
            for a in articles
            for chunk in chunk_article(a["id"], a["title"], a["body"], split=split, max_words=max_words)
        )

    def ranking(self, question: str, method: Literal["bm25", "vector"]) -> list[tuple[int, float]]:
        """(position, score) for every passage that clears this ranker's floor, best first."""
        if method == "bm25":
            scores = self.bm25.scores(words(question))
            passing = [i for i, s in enumerate(scores) if s > 0]
        else:
            q = trigram_vector(question)
            scores = [cosine(q, v) for v in self.vectors]
            passing = [i for i, s in enumerate(scores) if s >= VECTOR_FLOOR]
        return [(i, scores[i]) for i in sorted(passing, key=lambda i: (-scores[i], i))]

    def search(self, question: str, k: int = 3, method: Method = "hybrid") -> list[Hit]:
        """The top k passages for a question. Fewer, or none, when fewer clear the floors."""
        if method != "hybrid":
            return [
                Hit(self.chunks[i], score, {method: rank})
                for rank, (i, score) in enumerate(self.ranking(question, method)[:k], start=1)
            ]
        rankings = {m: [i for i, _ in self.ranking(question, m)] for m in ("bm25", "vector")}
        places = {m: {i: rank for rank, i in enumerate(r, start=1)} for m, r in rankings.items()}
        return [
            Hit(self.chunks[i], score, {m: places[m][i] for m in rankings if i in places[m]})
            for i, score in reciprocal_rank_fusion(rankings)[:k]
        ]
