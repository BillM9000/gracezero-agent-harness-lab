from __future__ import annotations

from toymodel import bpe, nextword
from toymodel.corpus import SUPPORT_REPLIES

PROMPT = "reset emails can take up to"


def test_training_is_repeatable():
    assert bpe.train(SUPPORT_REPLIES, 100) == bpe.train(SUPPORT_REPLIES, 100)


def test_a_common_word_is_one_token_and_an_unfamiliar_one_is_several():
    merges = bpe.train(SUPPORT_REPLIES, 100)
    [password] = bpe.encode("password", merges)
    [passphrase] = bpe.encode("passphrase", merges)
    assert password == ["password"]
    assert len(passphrase) > 1


def test_temperature_zero_always_gives_the_most_common_continuation():
    table = nextword.train(SUPPORT_REPLIES)
    runs = {nextword.continue_text(table, PROMPT, temperature=0, seed=s) for s in range(10)}
    assert len(runs) == 1
    assert runs.pop().startswith("an hour")  # common in the training text, and out of date


def test_sampling_varies_from_run_to_run_but_repeats_for_the_same_seed():
    table = nextword.train(SUPPORT_REPLIES)
    runs = [nextword.continue_text(table, PROMPT, seed=s) for s in range(10)]
    assert len(set(runs)) > 1
    assert any(r.startswith("ten minutes") for r in runs)
    assert nextword.continue_text(table, PROMPT, seed=3) == nextword.continue_text(table, PROMPT, seed=3)


def test_a_prompt_the_model_never_saw_gets_no_continuation():
    table = nextword.train(SUPPORT_REPLIES)
    assert nextword.continue_text(table, "the moon is made of") == ""
