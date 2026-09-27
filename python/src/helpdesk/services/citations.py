"""Checking an answer's citations against the passages it was given (chapter 9).

An answer cites a passage by its id in square brackets, such as [1#2], in the sentence the passage
supports. A citation written after the sentence's full stop, "Refunds are free. [1#2]" or
"Refunds are free. ([1#2])", belongs to that sentence too, not to the one after it. A citation with
no sentence to support, such as one that is the whole answer, is a problem: it vouches for nothing.
For every other citation this checks three things, cheapest first:

1. The passage exists in the knowledge base.
2. The answer was given it. A citation to a passage the model was never shown is made up, even
   when the id is real.
3. The sentence uses only its passages' words: every word the sentence uses, apart from stop words,
   appears in the passages the sentence cites. "Emails" and "email" count as the same word.

The third check compares words, not meaning, so it can't say that a passage supports a sentence.
It's strict on purpose. It catches a changed fact, such as "an hour" where the passage says "ten
minutes", because "hour" isn't in the passage. It also flags an honest paraphrase, which is why the
triage assistant is told to use the passages' own words: a flag means a person looks, not that the
sentence is wrong. It can't catch a sentence that drops a word, such as a "not", because every word
left is still in the passage, or one that rearranges the passage's words to say something else.
Whether a passage supports what a sentence means is for a person or a model judge (chapter 22). And
a sentence with no citation isn't checked at all; the report lists those, so a reviewer sees what
the check can't vouch for.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from helpdesk.services.retrieval import SENTENCE_END, words

CITATION = re.compile(r"\[(\d+#\d+)\]")
# Citations at the very start of a piece of the answer, once it's split after each full stop, each
# perhaps in parentheses or after a comma or semicolon: "[1#2]", "([1#2])", "([1#2], [2#3])".
LEADING_CITATIONS = re.compile(r"^(?:\s*[(,;]?\s*\[\d+#\d+\]\s*\)?)+")
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


def sentences(answer: str) -> list[str]:
    """The answer's sentences, each with its citations. Splitting after every full stop leaves a
    citation written after one at the start of the next piece, where it would vouch for the next
    sentence instead of its own, or, at the end of the answer, for nothing. So a run of citations
    at the start of a piece, parentheses and all, goes back onto the sentence before it."""
    found: list[str] = []
    for piece in SENTENCE_END.split(answer.strip()):
        lead = LEADING_CITATIONS.match(piece)
        if lead and found:
            found[-1] = f"{found[-1]} {lead.group().strip()}"
            piece = piece[lead.end() :].strip()
            if not piece:
                continue
        found.append(piece)
    return found


def check(answer: str, given: Mapping[str, str], known: Collection[str] | None = None) -> CitationReport:
    """Check every citation in an answer. given maps each passage id the answer was shown to that
    passage's text; known, when supplied, is every passage id in the knowledge base."""
    checked = 0
    problems: list[Problem] = []
    uncited: list[str] = []
    for sentence in sentences(answer):
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
        if not words(CITATION.sub(" ", sentence)):
            # Nothing before it to go back onto (the whole answer, or its first piece): no words to
            # check, so without this it would pass as checked while vouching for nothing.
            which = " and ".join(f"[{c}]" for c in cited) + (" have" if len(cited) > 1 else " has")
            problems.append(Problem(", ".join(cited), sentence, f"{which} no sentence to support"))
        elif support and missing:
            which = " and ".join(f"[{c}]" for c in cited) + (" don't" if len(cited) > 1 else " doesn't")
            problems.append(Problem(", ".join(cited), sentence, f"{which} say: {', '.join(missing)}"))
    return CitationReport(checked, tuple(problems), tuple(uncited))
