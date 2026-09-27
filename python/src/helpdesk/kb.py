"""Composition root for the knowledge base's command line (chapter 9).

python -m helpdesk.kb query "reset email never arrives"   the top passages, and each ranker's place for them
python -m helpdesk.kb query "..." --method bm25          one ranker alone: bm25 or vector
python -m helpdesk.kb eval                               recall at 3 on the golden set; fails below its floor
python -m helpdesk.kb eval --split article               the same, with each whole article as one passage
python -m helpdesk.kb cite "QUESTION" "ANSWER"           check an answer's citations against the passages
                                                         the question retrieves
python -m helpdesk.kb chunks [ARTICLE]                   the passages each article is split into
python -m helpdesk.kb size                               the knowledge base's size, against a token budget

Each run loads the sample knowledge base into a fresh in-memory database, so nothing is saved.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed
from helpdesk.services import citations, kb
from helpdesk.services.retrieval import METHODS, SPLITS, VECTOR_FLOOR, Index, Method, Split

GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "kb_questions.json"
# Anthropic's models page gives about 2.5 characters per token for its current tokenizer. It's an
# estimate for a size check; count with a token-counting endpoint before relying on a number.
CHARS_PER_TOKEN = 2.5


@dataclass
class Result:
    """How one ranking method did on the golden set."""

    method: str
    found: int = 0  # questions with an answer whose answering passage was in the top k
    answerable: int = 0
    empty: int = 0  # questions with no answer that got no passages, as they should
    unanswerable: int = 0
    words_sent: int = 0  # words in every passage returned, all questions together
    by_kind: dict[str, list[int]] = field(default_factory=dict)  # kind: [right, asked]
    misses: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.found / self.answerable if self.answerable else 1.0


def answered(question: dict[str, Any], hits: Sequence[Any]) -> bool:
    """A hit is a passage from the named article that contains the named words. A question with no
    answer is answered correctly by nothing at all."""
    answer = question["answer"]
    if answer is None:
        return not hits
    says = answer["says"].lower()
    return any(h.chunk.article_id == answer["article"] and says in h.chunk.text.lower() for h in hits)


def evaluate(index: Index, questions: Sequence[dict[str, Any]], k: int, method: Method) -> Result:
    result = Result(method)
    for q in questions:
        hits = index.search(q["question"], k, method)
        result.words_sent += sum(len(h.chunk.indexed.split()) for h in hits)
        right = answered(q, hits)
        tally = result.by_kind.setdefault(q["kind"], [0, 0])
        tally[0] += right
        tally[1] += 1
        if q["answer"] is None:
            result.unanswerable += 1
            result.empty += right
        else:
            result.answerable += 1
            result.found += right
        if not right:
            got = ", ".join(h.chunk.id for h in hits) or "nothing"
            wanted = (
                "nothing"
                if q["answer"] is None
                else f'article {q["answer"]["article"]} saying "{q["answer"]["says"]}"'
            )
            result.misses.append(f"  {q['id']} {q['question']}\n      wanted {wanted}; got {got}")
    return result


def run_eval(conn: Any, golden_path: Path, k: int | None, split: Split) -> int:
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    k = k or golden["k"]
    index = kb.build_index(conn, split=split)
    questions = golden["questions"]
    methods: tuple[Method, ...] = ("bm25", "vector", "hybrid")
    results = {m: evaluate(index, questions, k, m) for m in methods}
    print(f"Golden set: {golden_path.name}, {len(questions)} questions.")
    print(f"Passages: {len(index.chunks)}, split by {split}. Top {k} for each question.\n")
    print(f"{'':20}{'bm25':>8}{'vector':>8}{'hybrid':>8}")
    for kind in dict.fromkeys(q["kind"] for q in questions):
        cells = "".join(f"{r.by_kind[kind][0]:>5}/{r.by_kind[kind][1]:<2}" for r in results.values())
        print(f"{kind:20}{cells}")
    print(f"{f'recall at {k}':20}" + "".join(f"{r.found:>5}/{r.answerable:<2}" for r in results.values()))
    print(
        f"{'words sent, average':20}"
        + "".join(f"{r.words_sent / len(questions):>8.0f}" for r in results.values())
    )

    hybrid = results["hybrid"]
    if hybrid.misses:
        print("\nhybrid missed:")
        print("\n".join(hybrid.misses))
    floor = golden["floor"]
    empty_share = hybrid.empty / hybrid.unanswerable if hybrid.unanswerable else 1.0
    recall_ok = hybrid.recall >= floor["recall"]
    empty_ok = empty_share >= floor["no_answer_empty"]
    summary = (
        f"hybrid recall at {k} is {hybrid.recall:.0%} ({hybrid.found} of {hybrid.answerable}), floor "
        f"{floor['recall']:.0%}; {hybrid.empty} of {hybrid.unanswerable} questions with no answer got "
        f"nothing, floor {floor['no_answer_empty']:.0%}."
    )
    if recall_ok and empty_ok:
        print(f"\nPASS: {summary}")
        return 0
    print(f"\nFAIL: {summary}")
    print(
        "A change that lost these questions needs fixing, not the floor lowering. If a question is "
        "wrong, fix the question in the golden set and say why in the commit."
    )
    return 1


def run_query(conn: Any, question: str, k: int, method: Method) -> int:
    hits = kb.retrieve(conn, question, k, method)
    if not hits:
        print(f"Nothing clears the floors for: {question}")
        print(f"(bm25 needs a word in common; vector needs a cosine similarity of at least {VECTOR_FLOOR}.)")
        return 0
    print(f"Top {k} passages by {method} for: {question}")
    for hit in hits:
        places = ", ".join(f"{m} #{rank}" for m, rank in hit.ranks.items())
        where = f"{hit.chunk.title} > {hit.chunk.heading}" if hit.chunk.heading else hit.chunk.title
        print(f"  {hit.chunk.id:<5} {places:<20} {where}")
    return 0


def run_cite(conn: Any, question: str, answer: str) -> int:
    hits = kb.retrieve(conn, question)
    given = {h.chunk.id: h.chunk.indexed for h in hits}
    known = {c.id for c in kb.build_index(conn).chunks}
    report = citations.check(answer, given, known)
    print(f"Passages given for {question!r}: {', '.join(given) or 'none'}")
    for problem in report.problems:
        print(f"FAIL  {problem.reason}\n      in: {problem.sentence}")
    if report.ok:
        print(
            f"PASS  {report.checked} citation(s) checked; each exists, was given, "
            "and uses only its passage's words."
        )
    print(f"Not checked: {len(report.uncited)} sentence(s) cite nothing.")
    return 0 if report.ok else 1


def run_chunks(conn: Any, article: int | None, split: Split) -> int:
    index = kb.build_index(conn, split=split)
    shown = [c for c in index.chunks if article is None or c.article_id == article]
    if not shown:
        print(f"No article {article}. Articles are numbered 1 to {max(c.article_id for c in index.chunks)}.")
        return 1
    for chunk in shown:
        print(f"{chunk.id:<5} ({len(chunk.text.split())} words) {chunk.indexed}")
    return 0


def run_size(conn: Any, budget: int) -> int:
    articles = kb.articles(conn)
    whole = "".join(f"# {a['title']}\n\n{a['body']}\n\n" for a in articles)
    passages = len(kb.build_index(conn).chunks)
    tokens = round(len(whole) / CHARS_PER_TOKEN)
    print(
        f"Knowledge base: {len(articles)} articles, {passages} passages, {len(whole.split()):,} words, "
        f"{len(whole):,} characters."
    )
    estimate = f"{CHARS_PER_TOKEN} characters per token (an estimate; count before relying on it)"
    print(f"About {tokens:,} tokens, at {estimate}.")
    verdict = (
        "small enough to send whole with every question" if tokens <= budget else "too big to send whole"
    )
    print(f"That is {tokens / budget:.1%} of a {budget:,}-token budget: {verdict}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.kb")
    commands = parser.add_subparsers(dest="command", required=True)
    query = commands.add_parser("query", help="the top passages for a question")
    query.add_argument("question")
    query.add_argument("--method", choices=METHODS, default="hybrid")
    query.add_argument("-k", type=int, default=3)
    evaluation = commands.add_parser("eval", help="recall at k on the golden set; exits 1 below its floor")
    evaluation.add_argument("-k", type=int, help="passages per question (default: the golden set's k)")
    evaluation.add_argument("--split", choices=SPLITS, default="section")
    evaluation.add_argument("--golden", type=Path, default=GOLDEN)
    cite = commands.add_parser("cite", help="check an answer's citations against a question's passages")
    cite.add_argument("question")
    cite.add_argument("answer")
    chunks = commands.add_parser("chunks", help="the passages each article is split into")
    chunks.add_argument("article", nargs="?", type=int)
    chunks.add_argument("--split", choices=SPLITS, default="section")
    size = commands.add_parser("size", help="the knowledge base's size, against a token budget")
    size.add_argument("--budget", type=int, default=200_000)
    args = parser.parse_args(argv)

    conn = connect(":memory:")
    try:
        init_schema(conn)
        seed(conn)
        if args.command == "query":
            return run_query(conn, args.question, args.k, args.method)
        if args.command == "eval":
            return run_eval(conn, args.golden, args.k, args.split)
        if args.command == "cite":
            return run_cite(conn, args.question, args.answer)
        if args.command == "chunks":
            return run_chunks(conn, args.article, args.split)
        return run_size(conn, args.budget)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
