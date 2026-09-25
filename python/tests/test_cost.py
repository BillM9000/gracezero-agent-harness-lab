from __future__ import annotations

import pytest

from helpdesk.model.cost import PRICES_READ, call_cost, conversation, provider_of, read_on


def test_a_call_is_priced_per_million_tokens_with_output_dearer_than_input():
    # claude-opus-5-5 at $4 in and $20 out per million tokens (read 2026-09-22).
    assert call_cost("claude-opus-5-5", 1_000_000, 0) == pytest.approx(4.0)
    assert call_cost("claude-opus-5-5", 0, 1_000_000) == pytest.approx(20.0)
    assert call_cost("claude-opus-5-5", 2_300, 500) == pytest.approx(0.0192)


def test_every_turn_resends_the_history_so_input_grows():
    turns = conversation("claude-opus-5-5", system=2000, user=300, reply=500, turns=3)
    assert [t.input_tokens for t in turns] == [2300, 3100, 3900]
    assert all(t.output_tokens == 500 for t in turns)
    assert turns[2].cost > turns[1].cost > turns[0].cost


def test_an_unknown_model_names_the_ones_it_knows():
    with pytest.raises(ValueError, match="Known models: claude-fable-5-1, claude-haiku-4-5"):
        call_cost("gpt-unknown", 10, 10)


# Chapter 27: prompt caching and trimming, the two levers on a growing history.


def test_with_caching_each_turn_reads_the_last_request_and_writes_the_rest():
    turns = conversation("claude-opus-5-5", system=2000, user=300, reply=500, turns=3, cache=True)
    assert [(t.cache_read, t.cache_written) for t in turns] == [(0, 2300), (2300, 800), (3100, 800)]
    # Turn 2 on claude-opus-5-5 ($4 in): 2,300 read at 0.05x, 800 written at 1.25x, 500 out at $20.
    assert turns[1].cost == pytest.approx((2300 * 4 * 0.05 + 800 * 4 * 1.25 + 500 * 20) / 1_000_000)


def test_the_first_turn_costs_more_with_caching_and_every_later_one_less():
    plain = conversation("claude-opus-5-5", system=2000, user=300, reply=500, turns=10)
    cached = conversation("claude-opus-5-5", system=2000, user=300, reply=500, turns=10, cache=True)
    assert cached[0].cost > plain[0].cost
    assert all(c.cost < p.cost for c, p in zip(cached[1:], plain[1:], strict=True))


def test_a_request_shorter_than_the_models_minimum_is_not_cached():
    # claude-sonnet-5 caches nothing under 1,024 tokens, and says nothing about it.
    turns = conversation("claude-sonnet-5", system=500, user=100, reply=200, turns=3, cache=True)
    assert [(t.input_tokens, t.cache_written) for t in turns] == [(600, 0), (900, 0), (1200, 1200)]
    assert turns[0].cost == call_cost("claude-sonnet-5", 600, 200)


def test_trimming_sends_only_the_last_exchanges_and_is_priced_apart_from_caching():
    turns = conversation("claude-opus-5-5", system=2000, user=300, reply=500, turns=5, keep=2)
    assert [t.input_tokens for t in turns] == [2300, 3100, 3900, 3900, 3900]
    with pytest.raises(ValueError, match="not both"):
        conversation("claude-opus-5-5", system=2000, user=300, reply=500, turns=5, keep=2, cache=True)


def test_every_priced_model_has_its_cache_prices_and_minimum():
    from helpdesk.model.cost import CACHE_MIN_TOKENS, CACHE_READ, PRICES

    assert set(CACHE_READ) == set(CACHE_MIN_TOKENS) == set(PRICES)


# A second provider (chapter 18): its model is priced from its own pages, read on their own day.


def test_a_second_providers_model_is_priced_from_its_own_page():
    # gpt-6.1-sol at $2 in and $10 out per million tokens, short context (OpenAI's pricing page, read
    # 2026-10-01); the policy's output price for it is the same (test_agent_policy checks).
    assert call_cost("gpt-6.1-sol", 1_000_000, 0) == pytest.approx(2.0)
    assert call_cost("gpt-6.1-sol", 0, 1_000_000) == pytest.approx(10.0)
    assert (provider_of("gpt-6.1-sol"), read_on("gpt-6.1-sol")) == ("OpenAI", "2026-10-01")
    assert (provider_of("claude-sonnet-5"), read_on("claude-sonnet-5")) == ("Anthropic", PRICES_READ)
    with pytest.raises(ValueError, match="No provider lists 'gpt-unknown'"):
        provider_of("gpt-unknown")


def test_every_priced_model_has_exactly_one_provider():
    from helpdesk.model.cost import PRICES, PROVIDERS

    listed = [model for provider in PROVIDERS.values() for model in provider["models"]]
    assert sorted(listed) == sorted(PRICES)
    for provider in PROVIDERS.values():
        assert set(provider) == {"pricing", "caching", "read", "models"}
