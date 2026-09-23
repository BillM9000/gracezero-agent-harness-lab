from __future__ import annotations

import pytest

from helpdesk.model.mock import MockModel
from helpdesk.model.stops import IncompleteResponse, NotFinished, Refused, Truncated, final_text
from helpdesk.model.types import Message, ModelResponse

QUESTION = [Message("user", "When will my reset email arrive?")]


def ask(response: ModelResponse) -> str:
    model = MockModel([response])
    return final_text(model.complete(system="s", messages=QUESTION))


def test_a_finished_answer_comes_back_as_text():
    assert ask(ModelResponse(stop_reason="end_turn", text="Within ten minutes.")) == "Within ten minutes."
    assert ask(ModelResponse(stop_reason="stop_sequence", text="Within ten")) == "Within ten"


def test_a_refusal_is_not_an_answer_even_though_it_is_a_success():
    with pytest.raises(Refused, match="record it as its own event"):
        ask(ModelResponse(stop_reason="refusal"))


def test_a_cut_off_answer_is_never_returned_as_if_complete():
    with pytest.raises(Truncated, match="Do not use the partial text"):
        ask(ModelResponse(stop_reason="max_tokens", text="Reset emails can take up to"))
    with pytest.raises(Truncated, match="Send less"):
        ask(ModelResponse(stop_reason="model_context_window_exceeded", text="Reset emails"))


def test_a_tool_call_means_the_loop_is_not_done():
    with pytest.raises(NotFinished, match="Keep the loop going"):
        ask(ModelResponse(stop_reason="tool_use"))
    with pytest.raises(NotFinished):
        ask(ModelResponse(stop_reason="pause_turn"))


def test_an_unknown_stop_reason_fails_closed():
    with pytest.raises(IncompleteResponse, match="Unknown stop_reason 'something_new'"):
        final_text(ModelResponse(stop_reason="something_new", text="looks fine"))  # type: ignore[arg-type]
