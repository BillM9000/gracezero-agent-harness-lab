"""Retrieval over the knowledge base (chapter 9): passages, BM25, the vector stand-in, fusion."""

from __future__ import annotations

import math

import pytest

from helpdesk.data.seed import kb_articles
from helpdesk.services import kb
from helpdesk.services.errors import Invalid
from helpdesk.services.retrieval import (
    BM25,
    Index,
    chunk_article,
    cosine,
    pieces,
    reciprocal_rank_fusion,
    trigram_vector,
    words,
)

BODY = """## First heading

One paragraph. It has two sentences.

Another paragraph under the same heading.

## Second heading

It expires after 7 days."""


@pytest.fixture(scope="module")
def index() -> Index:
    return Index.build({"id": i, "title": t, "body": b} for i, t, b, _ in kb_articles())


def ids(hits) -> list[str]:
    return [hit.chunk.id for hit in hits]


def test_every_article_file_has_a_title_tags_and_headed_sections():
    articles = kb_articles()
    assert [a[0] for a in articles] == list(range(1, len(articles) + 1)), "article ids run 1, 2, 3, ..."
    for article_id, title, body, tags in articles:
        assert title and tags, article_id
        assert body.startswith("## "), f"article {article_id} should open with a '## ' heading"


def test_articles_split_at_their_own_headings_and_every_passage_says_where_it_came_from():
    chunks = chunk_article(7, "Some article", BODY)
    assert [c.id for c in chunks] == ["7#1", "7#2"]
    assert chunks[0].text == "One paragraph. It has two sentences. Another paragraph under the same heading."
    # "It expires after 7 days" means nothing alone; with its title and heading it says what expires.
    assert chunks[1].indexed == "Some article > Second heading: It expires after 7 days."


def test_a_question_can_find_a_passage_through_its_heading(index):
    # "Transferring ownership" is only in the heading of article 7's passage; its text says "hand it
    # to someone else". Without the heading in front, keyword search finds only article 8.
    assert ids(index.search("transferring ownership", 3, "bm25"))[0] == "7#2"


def test_a_long_section_is_split_at_sentence_ends_and_never_mid_sentence():
    paragraph = "One two three four five. Six seven eight nine ten. Eleven twelve."
    assert pieces([paragraph], 10) == ["One two three four five. Six seven eight nine ten.", "Eleven twelve."]
    assert pieces(["one two three four five six"], 3) == ["one two three four five six"]


def test_the_other_splits_make_whole_articles_or_single_sentences():
    assert [c.text for c in chunk_article(1, "T", BODY, split="article")] == [
        "First heading One paragraph. It has two sentences. Another paragraph under the same heading. "
        "Second heading It expires after 7 days."
    ]
    assert len(chunk_article(1, "T", BODY, split="sentence")) == 4


def test_words_drops_stop_words_and_keeps_negations_and_codes():
    assert words("Why can't I sign in? Error E-4012, not the 2FA code.") == [
        "can't",
        "sign",
        "error",
        "4012",
        "not",
        "2fa",
        "code",
    ]


def test_bm25_weights_a_rare_word_above_a_common_one():
    bm25 = BM25([["reset", "email"], ["reset", "invoice"], ["reset", "token"], ["export"]])
    email, invoice, _, _ = bm25.scores(["reset", "invoice"])
    assert invoice > email


def test_bm25_marks_down_a_longer_passage_with_the_same_matches():
    passages = [
        ["refund", "card"],
        ["refund", "card", "plan", "billing", "date", "owner"],
        ["export"],
        ["token"],
        ["invite"],
    ]
    short, long, *_ = BM25(passages).scores(["refund"])
    assert short > long > 0


def test_a_word_in_most_passages_adds_nothing_rather_than_counting_against_a_passage():
    bm25 = BM25([["settings", "export"], ["settings", "token"], ["settings", "invite"]])
    assert bm25.idf["settings"] == 0.0
    assert bm25.scores(["settings", "export"])[0] > 0


def test_bm25_scores_zero_for_a_passage_with_no_word_in_common():
    assert BM25([["reset", "email"], ["export"]]).scores(["invoice"]) == [0.0, 0.0]


def test_the_vector_stand_in_is_deterministic_and_puts_a_misspelling_near_the_word():
    assert trigram_vector("pasword") == trigram_vector("pasword")
    assert math.isclose(cosine(trigram_vector("password reset"), trigram_vector("password reset")), 1.0)
    typo = trigram_vector("pasword")
    assert cosine(typo, trigram_vector("password")) > 0.4 > cosine(typo, trigram_vector("invoice"))


def test_fusion_puts_a_passage_both_rankers_like_above_one_only_a_single_ranker_puts_first():
    # Passage 2 is second in both rankings; 1 and 3 are each first in one. With k = 60, agreement
    # wins: 2/62 is about 0.0323, and 1/61 about 0.0164.
    fused = reciprocal_rank_fusion({"bm25": [1, 2], "vector": [3, 2]})
    assert [item for item, _ in fused] == [2, 1, 3]
    assert math.isclose(fused[0][1], 2 / 62)


def test_fusion_finds_what_each_ranker_alone_misses(index):
    # Keyword search misses this one: "change" and "never" pull in other passages.
    question = "I never got the email to change my password"
    assert "1#2" not in ids(index.search(question, 3, "bm25"))
    assert "1#2" in ids(index.search(question, 3, "hybrid"))
    # The vector stand-in returns nothing at all for this one; keyword search finds it.
    question = "What happens if my card is declined?"
    assert index.search(question, 3, "vector") == []
    assert "9#3" in ids(index.search(question, 3, "hybrid"))


def test_known_limit_fusion_can_outvote_the_one_ranker_that_was_right(index):
    # Chapter 9 reports this. The error code is keyword search's first choice, but three passages
    # about signing in that both rankers like push it out of the top three.
    question = "getting error 2231 when I sign in"
    assert ids(index.search(question, 3, "bm25"))[0] == "4#3"
    assert "4#3" not in ids(index.search(question, 3, "hybrid"))


def test_a_question_the_knowledge_base_cannot_answer_gets_nothing_back(index):
    for question in ("What is the capital of France?", "Tell me a joke about cats"):
        for method in ("bm25", "vector", "hybrid"):
            assert index.search(question, 3, method) == [], (question, method)


def test_each_hit_says_where_each_ranker_placed_it(index):
    top = index.search("pasword reset email not arriving")[0]
    assert top.chunk.id == "1#1"
    assert top.ranks == {"bm25": 1, "vector": 2}


def test_retrieve_checks_its_arguments(conn):
    assert ids(kb.retrieve(conn, "E-4012"))[0] == "5#2"
    with pytest.raises(Invalid, match="question must not be empty"):
        kb.retrieve(conn, "  ")
    with pytest.raises(Invalid, match="k must be between"):
        kb.retrieve(conn, "refund", k=0)
    with pytest.raises(Invalid, match="method must be one of hybrid, bm25, vector"):
        kb.retrieve(conn, "refund", method="semantic")  # type: ignore[arg-type]
