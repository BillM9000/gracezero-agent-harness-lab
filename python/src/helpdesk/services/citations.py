"""Checking an answer's citations against the passages it was given (chapter 9).

An answer cites a passage by its id in square brackets, such as [1#2], in the sentence the passage
supports. For every citation this checks three things, cheapest first:

1. The passage exists in the knowledge base.
2. The answer was given it. A citation to a passage the model was never shown is made up, even
   when the id is real.
3. The passage supports the sentence: every word the sentence uses, apart from stop words, appears
   in the passages the sentence cites. "Emails" and "email" count as the same word.

The third check is strict on purpose. It catches a changed fact, such as "an hour" where the
passage says "ten minutes", because "hour" isn't in the passage. It also flags an honest
paraphrase, which is why the triage assistant is told to use the passages' own words: a flag means
a person looks, not that the sentence is wrong. It can't catch a sentence that drops a word, such
as a "not", because every word left is still in the passage. And a sentence with no citation isn't
checked at all; the report lists those, so a reviewer sees what the check can't vouch for.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from helpdesk.services.retrieval import SENTENCE_END, words

CITATION = re.compile(r"\[(\d+#\d+)\]")
# How a search result shows a passage to the model, one per line: "[1#2] Title > Heading: text".
PASSAGE_LINE = re.compile(r"^\[(\d+#\d+)\] (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Problem:
    citation: str
    sentence: str
    reason: str


@dataclass(frozen=True)
class CitationReport:
    checked: int
    problems: tuple[Problem, ...]
    uncited: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def passages_in(text: str) -> dict[str, str]:
    """The passages a search result showed, by id, read back from the result's text."""
    return dict(PASSAGE_LINE.findall(text))


def _same(word: str) -> str:
    """One spelling for a word and its plural, so "emails" in a sentence matches "email"."""
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _vocabulary(text: str) -> set[str]:
    return {_same(w) for w in words(text)}


def check(answer: str, given: Mapping[str, str], known: Collection[str] | None = None) -> CitationReport:
    """Check every citation in an answer. given maps each passage id the answer was shown to that
    passage's text; known, when supplied, is every passage id in the knowledge base."""
    checked = 0
    problems: list[Problem] = []
    uncited: list[str] = []
    for sentence in SENTENCE_END.split(answer.strip()):
        cited = CITATION.findall(sentence)
        if not cited:
            if words(sentence):
                uncited.append(sentence)
            continue
        support: set[str] = set()
        for citation in cited:
            checked += 1
            if known is not None and citation not in known:
                problems.append(
                    Problem(citation, sentence, f"[{citation}] doesn't exist in the knowledge base")
                )
            elif citation not in given:
                reason = f"[{citation}] wasn't among the passages this answer was given"
                problems.append(Problem(citation, sentence, f"{reason}, so it can't have come from it"))
            else:
                support |= _vocabulary(given[citation])
        missing = sorted(_vocabulary(CITATION.sub(" ", sentence)) - support)
        if support and missing:
            which = " and ".join(f"[{c}]" for c in cited) + (" don't" if len(cited) > 1 else " doesn't")
            problems.append(Problem(", ".join(cited), sentence, f"{which} say: {', '.join(missing)}"))
    return CitationReport(checked, tuple(problems), tuple(uncited))
