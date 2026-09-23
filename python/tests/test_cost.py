from __future__ import annotations

import pytest

from helpdesk.model.cost import call_cost, conversation


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
