"""The knowledge base's command line, and the retrieval check it runs (chapter 9).

python -m helpdesk.kb eval is the check: recall at 3 on the golden set, evals/kb_questions.json,
must stay at or above its floor, and questions the knowledge base can't answer must get nothing.
The tests below prove it fails when retrieval gets worse in either way.
"""

from __future__ import annotations

import pytest

from helpdesk import kb as cli
from helpdesk.services import retrieval
from helpdesk.services.retrieval import Chunk, Hit, Index


def run(capsys, *args: str) -> tuple[int, str]:
    code = cli.main(list(args))
    return code, capsys.readouterr().out


def test_the_golden_set_meets_its_floor(capsys):
    code, out = run(capsys, "eval")
    assert code == 0, out
    assert "PASS: hybrid recall at 3 is 88% (21 of 24), floor 85%" in out


def test_the_eval_fails_when_retrieval_loses_a_question_and_names_it(capsys, monkeypatch):
    # Someone "simplifies" search to the vector ranker alone. It loses one question, which the
    # floor was set to notice.
    search = Index.search
    monkeypatch.setattr(Index, "search", lambda self, q, k=3, method="hybrid": search(self, q, k, "vector"))
    code, out = run(capsys, "eval")
    assert code == 1
    assert "FAIL: hybrid recall at 3 is 83% (20 of 24), floor 85%" in out
    assert "q12 What happens if my card is declined?" in out
    assert "needs fixing, not the floor lowering" in out


def test_the_eval_fails_when_a_question_with_no_answer_gets_passages(capsys, monkeypatch):
    # Without the floor, the vector ranker always returns its three least-bad passages.
    monkeypatch.setattr(retrieval, "VECTOR_FLOOR", 0.0)
    code, out = run(capsys, "eval")
    assert code == 1
    assert "0 of 3 questions with no answer got nothing, floor 100%" in out
    assert "q25 What is the capital of France?" in out


def test_a_passage_from_the_right_article_without_the_answer_is_a_miss():
    question = {"answer": {"article": 1, "says": "ten minutes"}}
    wrong_passage = Hit(
        Chunk("1#3", 1, "Resetting your password", "Reset links expire", "Only one works."), 1.0, {}
    )
    right_passage = Hit(Chunk("1#2", 1, "Resetting your password", "", "Up to ten minutes."), 1.0, {})
    assert not cli.answered(question, [wrong_passage])
    assert cli.answered(question, [wrong_passage, right_passage])
    assert cli.answered({"answer": None}, [])


def test_whole_articles_find_more_and_send_more_than_sections(capsys):
    code, sections = run(capsys, "eval")
    code, articles = run(capsys, "eval", "--split", "article")
    assert "recall at 3            20/24   20/24   21/24" in sections
    assert "words sent, average       98      78      99" in sections
    assert "recall at 3            23/24   19/24   23/24" in articles
    assert "words sent, average      231     133     237" in articles


def test_cite_passes_a_supported_answer_and_fails_a_changed_fact(capsys):
    code, out = run(
        capsys, "cite", "reset email never arrives", "Reset emails can take up to ten minutes [1#2]."
    )
    assert code == 0, out
    # It checks words, not meaning, and says so.
    assert "PASS  1 citation(s) checked; each exists, was given, and uses only its passage's words." in out
    code, out = run(capsys, "cite", "reset email never arrives", "Reset emails can take up to an hour [1#2].")
    assert code == 1
    assert "FAIL  [1#2] doesn't say: hour" in out
    # A citation after the full stop is checked against the sentence it follows.
    code, out = run(capsys, "cite", "reset email never arrives", "Refunds are instant and free. [1#2]")
    assert code == 1
    assert "FAIL  [1#2] doesn't say: free, instant, refund" in out


def test_size_says_whether_the_knowledge_base_fits_a_budget(capsys):
    code, out = run(capsys, "size")
    assert "Knowledge base: 14 articles, 41 passages" in out
    assert "small enough to send whole" in out
    code, out = run(capsys, "size", "--budget", "1000")
    assert "too big to send whole" in out


def test_query_says_when_nothing_clears_the_floors(capsys):
    code, out = run(capsys, "query", "Tell me a joke about cats")
    assert code == 0
    assert "Nothing clears the floors" in out


@pytest.mark.parametrize("article", [0, 99])
def test_chunks_names_the_articles_that_exist(capsys, article):
    code, out = run(capsys, "chunks", str(article))
    assert code == 1
    assert "Articles are numbered 1 to 14" in out
