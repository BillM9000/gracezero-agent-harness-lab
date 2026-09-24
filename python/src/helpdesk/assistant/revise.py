"""Evaluator and optimizer (chapter 14): one side drafts, the other checks the draft and sends back
what's wrong, and the draft is revised until it passes or the rounds run out.

The drafter is the triage assistant, in one conversation that carries every round, so each
revision sees its earlier draft and the feedback on it. The evaluator is code: chapter 9's citation
check, run against the passages the conversation was given. Anthropic's "Building effective agents"
describes the pattern with a model as the evaluator; a check in code gives the same verdict every
time and costs nothing, so use one wherever the criteria can be written down.

The loop stops for one of three reasons, and says which:
- "passed": the check found no problems;
- "unchanged": the new draft is the same as the last one, so another round can't help;
- "limit": max_rounds drafts were checked and the last still fails.
Only "passed" is accepted. Anything else goes to a person with the problems still listed; a draft
that never passed is never handed on as if it had.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from helpdesk.assistant.agent import run_agent
from helpdesk.assistant.tools import Toolbox, passages_given
from helpdesk.model.types import Message, ModelClient
from helpdesk.services import citations
from helpdesk.services.citations import CitationReport

# Three drafts: the first, and two chances to act on feedback. Each round resends the whole
# conversation, so every round costs more than the one before.
MAX_ROUNDS = 3


@dataclass(frozen=True)
class Draft:
    round: int
    answer: str
    report: CitationReport


@dataclass(frozen=True)
class Revision:
    drafts: tuple[Draft, ...]
    stopped: str  # "passed", "unchanged" or "limit"
    transcript: tuple[Message, ...]

    @property
    def accepted(self) -> bool:
        return self.stopped == "passed"

    @property
    def answer(self) -> str:
        return self.drafts[-1].answer


def feedback(report: CitationReport) -> str:
    """What the evaluator sends back: every problem, where it is, and what to do about it."""
    lines = [f"The citation check found {len(report.problems)} problem(s) in your draft:"]
    lines += [f"- {problem.reason}, in: {problem.sentence}" for problem in report.problems]
    lines.append(
        "Revise the draft. Use the cited passage's own words, or leave the claim out. Reply with the "
        "whole draft again."
    )
    return "\n".join(lines)


def revise(
    model: ModelClient,
    tools: Toolbox,
    *,
    system: str,
    task: str,
    known: Collection[str],
    max_rounds: int = MAX_ROUNDS,
    max_turns: int = 6,
) -> Revision:
    """Draft, check and revise, at most max_rounds times. known is every passage id in the knowledge
    base, so a citation to a passage that doesn't exist is named as that."""
    drafts: list[Draft] = []
    transcript: tuple[Message, ...] = ()
    request = task
    for number in range(1, max_rounds + 1):
        run = run_agent(model, tools, system=system, task=request, max_turns=max_turns, history=transcript)
        transcript = run.transcript
        report = citations.check(run.answer, passages_given(transcript), known)
        unchanged = bool(drafts) and run.answer == drafts[-1].answer
        drafts.append(Draft(number, run.answer, report))
        if report.ok:
            return Revision(tuple(drafts), "passed", transcript)
        if unchanged:
            return Revision(tuple(drafts), "unchanged", transcript)
        request = feedback(report)
    return Revision(tuple(drafts), "limit", transcript)
