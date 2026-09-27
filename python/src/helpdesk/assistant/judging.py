"""Model judges (chapter 22): a model grading what string matching can't, against a rubric, with
every verdict checked before it counts.

Chapter 21's graders check facts, actions and citations in code. Whether a reply takes up what the
customer asked, or treats them well, takes judgment, so a model grades it. A judge is a model like
any other, so this module treats what it writes as data to check, never as a pass:

- A rubric (evals/rubrics/*.json) is a list of criteria, each one question with what passes and
  what fails. The judge answers one criterion per call, in a fresh conversation, so its verdict on
  one criterion can't lean on another.
- The judge is given what the writer was given: the tool results saved with the reply. It grades
  against that, never against what it knows or what the helpdesk holds now.
- It may answer "unknown" when that data isn't enough. Unknown is never a pass: a person decides.
- A verdict must match the Verdict schema exactly: one JSON object naming the criterion it was
  asked about, pass, fail or unknown, a reason, and any quotation word for word from the text it
  judged. Anything else, and any response that isn't a finished answer, is an error: counted, sent
  to a person, and never a pass.

Judging the judge: Agreement counts its verdicts against a person's labels on the same replies,
false passes and false fails apart, beside what a judge that passed everything would score.
second_slot says what a person reads when nobody has labeled the replies yet.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from helpdesk.assistant.agent import run_agent
from helpdesk.assistant.grading import found
from helpdesk.assistant.revise import feedback as citation_feedback
from helpdesk.assistant.tools import Toolbox, passages_given
from helpdesk.model.stops import IncompleteResponse, final_text
from helpdesk.model.types import Message, ModelClient
from helpdesk.services import citations

# --- Rubrics.


@dataclass(frozen=True)
class Criterion:
    id: str
    question: str
    passes: str
    fails: str


@dataclass(frozen=True)
class Rubric:
    id: str
    subject: str  # what is judged, in words
    given: str  # what the writer was given, in words: the judge's ground truth
    criteria: tuple[Criterion, ...]


def load_rubric(path: Path) -> Rubric:
    """A rubric from its JSON file. An unknown field, a missing one or a repeated criterion is an
    error, never a skip: a misspelled "fail" would otherwise leave the judge without it."""
    data = json.loads(path.read_text(encoding="utf-8"))
    where = f"{path.parent.name}/{path.name}"
    fields(data, {"id", "subject", "given", "criteria"}, where)
    criteria = []
    for n, item in enumerate(data["criteria"]):
        fields(item, {"id", "question", "pass", "fail"}, f"{where}: criteria[{n}]")
        criteria.append(Criterion(item["id"], item["question"], item["pass"], item["fail"]))
    ids = [c.id for c in criteria]
    if not ids:
        raise ValueError(f"{where}: a rubric needs at least one criterion.")
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise ValueError(
            f"{where}: criterion {', '.join(repeated)} appears more than once; give each its own id."
        )
    return Rubric(data["id"], data["subject"], data["given"], tuple(criteria))


def fields(data: Any, wanted: set[str], where: str) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"{where}: must be a JSON object.")
    unknown, missing = sorted(set(data) - wanted), sorted(wanted - set(data))
    if unknown or missing:
        problems = [f"unknown field(s) {', '.join(unknown)}"] if unknown else []
        problems += [f"missing {', '.join(missing)}"] if missing else []
        raise ValueError(f"{where}: {'; '.join(problems)}. The fields are {', '.join(sorted(wanted))}.")
    empty = sorted(k for k in wanted if k != "criteria" and not str(data[k]).strip())
    if empty:
        raise ValueError(f"{where}: {', '.join(empty)} is empty.")


# --- Verdicts.


class Verdict(BaseModel):
    """One criterion's verdict, as the judge must write it. The JSON Schema the judge is shown is
    generated from this class, so what it's asked for and what's accepted can't drift apart."""

    model_config = ConfigDict(extra="forbid", strict=True)

    criterion: str
    verdict: Literal["pass", "fail", "unknown"]
    reason: str
    quote: str | None = None


SCHEMA = json.dumps(Verdict.model_json_schema(), separators=(",", ":"))


class MalformedVerdict(ValueError):
    """What the judge wrote isn't a verdict this code accepts. It's an error, never a pass."""


def once_each(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """An object whose keys are each given once. json.loads keeps the last of a repeated key, so
    "verdict": "fail" then "verdict": "pass" would read as a pass."""
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise MalformedVerdict(f'it gives "{key}" more than once')
        data[key] = value
    return data


def read_verdict(text: str, criterion: Criterion, judged: str) -> Verdict:
    """The judge's answer as a Verdict, or MalformedVerdict saying what's wrong with it."""
    try:
        data = json.loads(text, object_pairs_hook=once_each)
    except json.JSONDecodeError as error:
        raise MalformedVerdict(f"not one JSON object ({error.msg}, at character {error.pos})") from None
    try:
        verdict = Verdict.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "the answer"
        raise MalformedVerdict(f"{where}: {first['msg']}") from None
    if verdict.criterion != criterion.id:
        raise MalformedVerdict(f'asked about "{criterion.id}", it answered about "{verdict.criterion}"')
    if not verdict.reason.strip():
        raise MalformedVerdict("the reason is empty")
    if verdict.quote is not None and not (verdict.quote.strip() and found(verdict.quote, judged)):
        raise MalformedVerdict(f'it quotes "{verdict.quote}", which isn\'t in the text it judged')
    return verdict


def request(rubric: Rubric, criterion: Criterion, text: str, given: Sequence[str]) -> str:
    """The one message a judge gets for one criterion: the question, the ground truth, the text,
    and the schema. Text and data go in as JSON strings, like everything customers write (chapter 20)."""
    data = "\n".join(json.dumps(item, ensure_ascii=False) for item in given) or "(none)"
    return "\n".join(
        [
            f"You are judging {rubric.subject}.",
            "",
            f'Criterion "{criterion.id}": {criterion.question}',
            f"It passes when {criterion.passes}.",
            f"It fails when {criterion.fails}.",
            "",
            f"The data the writer was given ({rubric.given}):",
            data,
            "",
            "The text to judge:",
            json.dumps(text, ensure_ascii=False),
            "",
            f"Answer with one JSON object that matches this JSON Schema: {SCHEMA}",
            f'Set "criterion" to "{criterion.id}". Answer "unknown" if the data above isn\'t enough to '
            'decide. Put any words you quote from the text in "quote", exactly as they appear.',
        ]
    )


@dataclass(frozen=True)
class Judgment:
    """One criterion, judged: a verdict, or the error that stands in for one."""

    criterion: str
    verdict: Verdict | None
    error: str | None = None

    @property
    def outcome(self) -> str:
        """pass, fail, unknown, or error when there's no verdict to read."""
        return "error" if self.verdict is None else self.verdict.verdict

    @property
    def why(self) -> str:
        if self.verdict is None:
            return str(self.error)
        quoted = f' ("{self.verdict.quote}")' if self.verdict.quote else ""
        return self.verdict.reason + quoted


def judge_one(
    model: ModelClient,
    definition: Mapping[str, Any],
    rubric: Rubric,
    criterion: Criterion,
    text: str,
    given: Sequence[str],
) -> Judgment:
    """Ask one criterion, in a conversation of its own, and check the answer."""
    message = Message("user", request(rubric, criterion, text, given))
    try:
        response = model.complete(system=definition["system"], messages=[message])
        return Judgment(criterion.id, read_verdict(final_text(response), criterion, text))
    except IncompleteResponse as stop:
        return Judgment(criterion.id, None, f"no verdict: {stop}")
    except MalformedVerdict as bad:
        return Judgment(criterion.id, None, f"malformed verdict: {bad}")


@dataclass(frozen=True)
class Assessment:
    """Every criterion of a rubric, judged for one text."""

    judgments: tuple[Judgment, ...]

    @property
    def outcome(self) -> str:
        """fail when any criterion failed; person when none failed but one is unknown or an error,
        because a verdict nobody could read is not a pass; pass only when every criterion passed."""
        outcomes = [j.outcome for j in self.judgments]
        if "fail" in outcomes:
            return "fail"
        if any(o in ("unknown", "error") for o in outcomes):
            return "person"
        return "pass"

    def of(self, criterion: str) -> Judgment:
        return next(j for j in self.judgments if j.criterion == criterion)


def judge(
    model_for: Callable[[Criterion], ModelClient],
    definition: Mapping[str, Any],
    rubric: Rubric,
    text: str,
    given: Sequence[str],
) -> Assessment:
    """Every criterion, each in its own call. model_for gives the client for a criterion: the same
    real model every time, or the mock with that criterion's scripted answer."""
    return Assessment(
        tuple(judge_one(model_for(c), definition, rubric, c, text, given) for c in rubric.criteria)
    )


# --- Judging the judge: its verdicts against a person's labels.

LABELS = ("pass", "fail")


@dataclass
class Agreement:
    """A judge's verdicts on labeled texts, counted against the person's labels. A false pass, the
    judge passing what the person failed, is kept apart from a false fail: in a gate, the first lets
    a bad reply through and the second only costs a second look."""

    judged: int = 0
    agree: int = 0
    false_pass: int = 0
    false_fail: int = 0
    unknown: int = 0
    errors: int = 0
    person_passed: int = 0  # labels the person passed: a judge that passed everything agrees on these

    def add(self, outcome: str, label: str) -> None:
        if label not in LABELS:
            raise ValueError(f"a person's label is pass or fail, not {label!r}")
        self.judged += 1
        self.person_passed += label == "pass"
        if outcome == "unknown":
            self.unknown += 1
        elif outcome == "error":
            self.errors += 1
        elif outcome == label:
            self.agree += 1
        elif outcome == "pass":
            self.false_pass += 1
        else:
            self.false_fail += 1


def settled(judge_outcome: str, person: str | None) -> str:
    """The grade that counts, with two slots: a person's label wins wherever there is one; without
    one, the judge's outcome stands, and one that isn't pass or fail waits for a person."""
    if person is not None:
        return person
    return judge_outcome if judge_outcome in ("pass", "fail") else "person"


def second_slot(outcomes: Mapping[str, str], *, share: float, seed: int) -> list[tuple[str, str]]:
    """What a person reads when nobody has labeled these texts: every one the judge couldn't settle,
    and a random share of the ones it passed, because a false pass is the mistake nothing after the
    judge will catch. outcomes maps each text's id to its Assessment outcome."""
    chosen = [(i, "the judge couldn't settle it") for i, o in outcomes.items() if o == "person"]
    passed = sorted(i for i, o in outcomes.items() if o == "pass")
    count = min(len(passed), max(1, round(share * len(passed)))) if passed and share > 0 else 0
    chosen += [(i, "a sampled pass") for i in sorted(random.Random(seed).sample(passed, count))]
    return chosen


# --- A judge in the loop: evaluator and optimizer (chapter 14) with a model as the evaluator.

MAX_ROUNDS = 3


@dataclass(frozen=True)
class Round:
    number: int
    draft: str
    report: citations.CitationReport
    assessment: Assessment | None  # None when the citation check failed, so the judge wasn't asked


@dataclass(frozen=True)
class JudgedRevision:
    rounds: tuple[Round, ...]
    stopped: str  # "passed", "person", "unchanged" or "limit"
    transcript: tuple[Message, ...] = field(default=())

    @property
    def accepted(self) -> bool:
        return self.stopped == "passed"


def judge_feedback(assessment: Assessment) -> str:
    failed = [j for j in assessment.judgments if j.outcome == "fail"]
    lines = [f"A reviewer failed your draft on {len(failed)} point(s):"]
    lines += [f"- {j.criterion}: {j.why}" for j in failed]
    lines.append("Revise the draft. Keep its citations. Reply with the whole draft again.")
    return "\n".join(lines)


def revise_with_judge(
    drafter: ModelClient,
    tools: Toolbox,
    judge_for: Callable[[int, Criterion], ModelClient],
    judge_definition: Mapping[str, Any],
    rubric: Rubric,
    *,
    system: str,
    task: str,
    known: Collection[str],
    max_rounds: int = MAX_ROUNDS,
    max_turns: int = 6,
) -> JudgedRevision:
    """Draft, check, judge and revise, at most max_rounds times. The citation check runs first,
    because code is cheaper and gives the same answer every time; the judge sees only drafts that
    pass it, with the tool results the drafter had. A judge that can't settle a criterion stops the
    loop for a person. judge_for gives the judge's client for a round and a criterion."""
    rounds: list[Round] = []
    transcript: tuple[Message, ...] = ()
    request_text = task
    for number in range(1, max_rounds + 1):
        run = run_agent(
            drafter, tools, system=system, task=request_text, max_turns=max_turns, history=transcript
        )
        transcript = run.transcript
        unchanged = bool(rounds) and run.answer == rounds[-1].draft
        report = citations.check(run.answer, passages_given(transcript), known)
        if not report.ok:
            rounds.append(Round(number, run.answer, report, None))
            if unchanged:
                return JudgedRevision(tuple(rounds), "unchanged", transcript)
            request_text = citation_feedback(report)
            continue
        given = results_of(transcript)
        assessment = judge(lambda c, n=number: judge_for(n, c), judge_definition, rubric, run.answer, given)
        rounds.append(Round(number, run.answer, report, assessment))
        if assessment.outcome == "pass":
            return JudgedRevision(tuple(rounds), "passed", transcript)
        if assessment.outcome == "person":
            return JudgedRevision(tuple(rounds), "person", transcript)
        if unchanged:
            return JudgedRevision(tuple(rounds), "unchanged", transcript)
        request_text = judge_feedback(assessment)
    return JudgedRevision(tuple(rounds), "limit", transcript)


def results_of(transcript: Iterable[Message]) -> list[str]:
    """Every tool result in a run, in order: what the drafter was given, and so the judge's ground truth."""
    return [result.content for message in transcript for result in message.tool_results]
