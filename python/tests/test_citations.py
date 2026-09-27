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


def test_a_citation_after_the_full_stop_at_the_end_is_checked_against_its_sentence():
    # Split after the full stop, "[1#2]" was a sentence of its own with no words, so the false
    # sentence before it was checked against nothing and the answer passed.
    report = check("Refunds are instant and free. [1#2]", GIVEN, KNOWN)
    assert not report.ok
    assert [(p.sentence, p.reason) for p in report.problems] == [
        ("Refunds are instant and free. [1#2]", "[1#2] doesn't say: free, instant, refund")
    ]
    # In parentheses too: "([1#2])" once kept the citation off the sentence, and passed.
    for after, reason in (
        ("([1#2])", "[1#2] doesn't say: free, instant, refund"),
        ("([1#2]).", "[1#2] doesn't say: free, instant, refund"),
        ("([1#2], [2#3])", "[1#2] and [2#3] don't say: free, instant"),
    ):
        report = check(f"Refunds are instant and free. {after}", GIVEN, KNOWN)
        assert [(p.sentence, p.reason) for p in report.problems] == [
            (f"Refunds are instant and free. {after.rstrip('.')}", reason)
        ]
        assert report.uncited == ()


def test_a_citation_with_no_sentence_to_support_is_a_problem():
    # With no sentence before it to go back onto (the whole answer, or its first piece), a citation
    # has no words to check, and once passed as checked while vouching for nothing.
    for answer, sentence, reason in (
        ("[1#2]", "[1#2]", "[1#2] has no sentence to support"),
        ("[1#2] [2#3]", "[1#2] [2#3]", "[1#2] and [2#3] have no sentence to support"),
        (
            "[1#2]. Reset emails can take up to ten minutes [1#2].",
            "[1#2].",
            "[1#2] has no sentence to support",
        ),
    ):
        report = check(answer, GIVEN, KNOWN)
        assert [(p.sentence, p.reason) for p in report.problems] == [(sentence, reason)]


def test_a_citation_after_the_full_stop_mid_answer_stays_with_its_own_sentence():
    # Split after the full stop, each [1#2] went to the sentence after it: the first vouched for
    # "Check your spam folder." and the false sentence about refunds went unchecked.
    report = check("Refunds are instant and free. [1#2] Check your spam folder. [1#2]", GIVEN, KNOWN)
    assert report.checked == 2
    assert "Refunds are instant and free. [1#2]" in [p.sentence for p in report.problems]
    assert report.uncited == ()


def test_citations_after_the_full_stop_all_go_back_to_the_sentence_they_follow():
    # The sentence needs both passages' words, so both citations must come back to it.
    answer = "Reset emails can take up to ten minutes, and refunds are not automatic. [1#2] [2#3] Hello."
    report = check(answer, GIVEN)
    assert report.ok
    assert report.checked == 2
    assert report.uncited == ("Hello.",)


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
