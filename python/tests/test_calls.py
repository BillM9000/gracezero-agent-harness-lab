"""A record of every model call (chapter 26): one line a call, however it ended, with what it cost
and a fingerprint of the prompt and tools instead of the conversation.

Everything here runs the mock, or a fake client that raises.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from helpdesk import calls as calls_command
from helpdesk import gate
from helpdesk.model.budget import Budget, BudgetReached, prompt_json
from helpdesk.model.calls import OUTCOMES, CallLog, fingerprint, outcome_of, read, summary
from helpdesk.model.mock import MockModel
from helpdesk.model.types import Message, ModelResponse, Usage

CUSTOMER = "My card number is on the invoice, please refund me"


def ask(model: Any, text: str = "Hello") -> ModelResponse:
    return model.complete(system="You help.", messages=[Message("user", text)])


def recording(tmp_path: Path, cap: float | None = None) -> tuple[Budget, Path]:
    path = tmp_path / "records" / "calls.jsonl"
    return Budget(cap, 2.5, CallLog(path, "test")), path


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_every_call_through_a_recording_budget_is_one_line_with_its_tokens_and_cost(tmp_path):
    budget, path = recording(tmp_path)
    budget.part = "tasks"
    model = budget.wrap(
        MockModel([ModelResponse("end_turn", "Done.", usage=Usage(1000, 500))]), "claude-opus-5-5", 1000
    )
    ask(model)
    [line] = lines(path)
    assert (line["part"], line["model"], line["outcome"]) == ("tasks", "claude-opus-5-5", "ok")
    assert (line["input_tokens"], line["output_tokens"], line["tokens_from"]) == (1000, 500, "provider")
    assert round(line["usd"], 4) == 0.014 == round(budget.spent.usd, 4)


def test_the_mocks_tokens_are_marked_as_estimates(tmp_path):
    budget, path = recording(tmp_path)
    ask(budget.wrap(MockModel([ModelResponse("end_turn", "x" * 250)]), "claude-sonnet-5", 1000))
    [line] = lines(path)
    assert (line["output_tokens"], line["tokens_from"]) == (100, "estimate")


@pytest.mark.parametrize(
    ("stop", "outcome"),
    [("refusal", "refusal"), ("max_tokens", "cut off"), ("model_context_window_exceeded", "cut off")],
)
def test_a_refusal_and_a_cut_off_answer_are_failures_though_they_arrive_as_responses(tmp_path, stop, outcome):
    budget, path = recording(tmp_path)
    ask(budget.wrap(MockModel([ModelResponse(stop, "Partial")]), "claude-opus-5-5", 1000))
    [line] = lines(path)
    assert (line["outcome"], line["stop_reason"]) == (outcome, stop)
    assert outcome_of("end_turn") == outcome_of("tool_use") == "ok"


def test_an_error_is_recorded_with_its_type_and_still_raised(tmp_path):
    class Overloaded(Exception):
        pass

    class Failing:
        def complete(self, **_: Any) -> ModelResponse:
            raise Overloaded("529")

    budget, path = recording(tmp_path)
    with pytest.raises(Overloaded):
        ask(budget.wrap(Failing(), "claude-opus-5-5", 1000))
    [line] = lines(path)
    assert (line["outcome"], line["error"], line["tokens_from"]) == ("error", "Overloaded", "none")
    assert line["usd"] == 0


def test_a_call_the_cap_refuses_is_recorded_and_never_made(tmp_path):
    budget, path = recording(tmp_path, cap=0.10)
    inner = MockModel([ModelResponse("end_turn", "Done.")])
    with pytest.raises(BudgetReached):
        ask(budget.wrap(inner, "claude-opus-5-5", 16000))
    [line] = lines(path)
    assert (line["outcome"], line["usd"]) == ("over the cap", 0)
    assert inner.calls == []


def test_the_record_holds_a_fingerprint_of_the_prompt_and_tools_and_none_of_the_conversation(tmp_path):
    budget, path = recording(tmp_path)
    script = [ModelResponse("end_turn", "Done."), ModelResponse("end_turn", "Done.")]
    model = budget.wrap(MockModel(script), "claude-opus-5-5", 1000)
    ask(model, CUSTOMER)
    ask(model, "A different customer, a different question")
    text = path.read_text(encoding="utf-8")
    assert "card number" not in text and "You help." not in text
    first, second = lines(path)
    # The same prompt and tools, whatever the conversation: one fingerprint, the prompt's own.
    assert first["prompt"] == second["prompt"] == fingerprint(prompt_json("You help.", ()))
    assert fingerprint(prompt_json("You help, warmly.", ())) != first["prompt"]


def test_a_budget_without_a_log_records_nothing(tmp_path):
    budget = Budget(None, 2.5)
    ask(budget.wrap(MockModel([ModelResponse("end_turn", "Done.")]), "claude-opus-5-5", 1000))
    assert list(tmp_path.iterdir()) == []


def test_the_summary_counts_by_part_and_model_and_names_each_kind_of_failure(tmp_path):
    budget, path = recording(tmp_path)
    budget.part = "tasks"
    script = [ModelResponse("end_turn", "a"), ModelResponse("refusal", ""), ModelResponse("max_tokens", "b")]
    model = budget.wrap(MockModel(script), "claude-opus-5-5", 1000)
    for _ in script:
        ask(model)
    out = "\n".join(summary(read(path), 2.5))
    assert "3 calls from 1 run of test." in out
    assert "tasks  claude-opus-5-5      3" in out
    assert "Failed: 1 cut off, 1 refusal." in out
    assert set(OUTCOMES) == {"ok", "refusal", "cut off", "error", "over the cap"}


def test_a_line_that_isnt_a_call_is_refused_with_its_number(tmp_path):
    path = tmp_path / "calls.jsonl"
    path.write_text('{"at": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"calls.jsonl:1: not a call record"):
        read(path)


def test_a_gate_run_records_every_call_it_counts(tmp_path, capsys):
    path = tmp_path / "calls.jsonl"
    assert gate.main(["run", "--suite", "reasons", "--record", str(path)]) == 0
    found = read(path)
    assert len(found) == 45 and {c.part for c in found} == {"reasons"}
    assert f"Recorded 45 calls in {path.as_posix()}." in capsys.readouterr().out


def test_the_command_sums_up_a_record(tmp_path, capsys):
    path = tmp_path / "calls.jsonl"
    gate.main(["run", "--suite", "reasons", "--record", str(path)])
    capsys.readouterr()
    assert calls_command.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "45 calls from 1 run of gate run." in out
    assert "estimated at 2.5 characters a token; the mock reports none." in out
    assert calls_command.main([str(tmp_path / "missing.jsonl")]) == 1
