"""Checking an answer's citations against the passages it was given (chapter 9)."""

from __future__ import annotations

from helpdesk.services.citations import check, passages_in

GIVEN = {
    "1#2": "Resetting your password > If the reset email doesn't arrive: Reset emails can take up to ten "
    "minutes to arrive, and they sometimes land in the spam folder.",
    "2#3": "Changing your plan > Refunds: Refunds are not automatic. An owner can request one within "
    "14 days.",
}
KNOWN = {"1#1", "1#2", "1#3", "2#3", "5#2"}


def reasons(answer: str) -> list[str]:
    return [problem.reason for problem in check(answer, GIVEN, KNOWN).problems]


def test_a_sentence_in_its_passage_s_own_words_passes():
    report = check("Reset emails can take up to ten minutes to arrive [1#2].", GIVEN, KNOWN)
    assert report.ok
    assert report.checked == 1


def test_a_changed_fact_is_caught_and_the_word_named():
    # Chapter 2's toy model said "an hour". The passage says ten minutes.
    assert reasons("Reset emails can take up to an hour [1#2].") == ["[1#2] doesn't say: hour"]


def test_a_citation_to_a_passage_that_does_not_exist_is_caught():
    assert reasons("Refunds are not automatic [9#9].") == ["[9#9] doesn't exist in the knowledge base"]


def test_a_citation_to_a_real_passage_the_answer_was_not_given_is_caught():
    assert reasons("Refunds are not automatic [5#2].") == [
        "[5#2] wasn't among the passages this answer was given, so it can't have come from it"
    ]


def test_a_sentence_citing_two_passages_may_use_words_from_both():
    report = check(
        "Reset emails can take up to ten minutes [1#2], and refunds are not automatic [2#3].", GIVEN
    )
    assert report.ok
    assert report.checked == 2


def test_an_added_not_is_caught_because_the_passage_has_no_not():
    assert reasons("Reset emails do not land in the spam folder [1#2].") == ["[1#2] doesn't say: not"]


def test_known_limit_a_dropped_not_passes():
    # Chapter 9 reports this. Every word left in the sentence is in the passage, so a sentence that
    # reverses the passage by leaving "not" out passes. A person or a model judge has to catch it.
    assert check("Refunds are automatic [2#3].", GIVEN, KNOWN).ok


def test_sentences_with_no_citation_are_listed_but_not_failed():
    report = check("Hello, and sorry for the trouble. Reset emails can take up to ten minutes [1#2].", GIVEN)
    assert report.ok
    assert report.uncited == ("Hello, and sorry for the trouble.",)


def test_passages_are_read_back_from_a_search_result():
    result = "[1#2] Resetting your password > If the reset email doesn't arrive: text\n[11#2] Email: more"
    assert passages_in(result) == {
        "1#2": "Resetting your password > If the reset email doesn't arrive: text",
        "11#2": "Email: more",
    }
