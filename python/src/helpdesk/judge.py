"""Composition root for model judges (chapter 22).

python -m helpdesk.judge check                     the rubrics, the labeled replies and the mock's
                                                   scripts are sound, every malformed answer is
                                                   refused, and agreement can tell a rubber stamp
python -m helpdesk.judge calibrate                 judge the labeled replies (evals/judged.json) and
                                                   count the verdicts against the person's labels
python -m helpdesk.judge calibrate --judge second  the same with agents/judge-second.toml
python -m helpdesk.judge compare                   both judges on the same labels, paired by label
python -m helpdesk.judge revise                    evaluator and optimizer with a judge as evaluator
python -m helpdesk.judge doc ../AGENTS.md          an instruction file against rubrics/instructions.json

--judge same uses agents/judge.toml, the triage assistant's own model in a fresh context; --judge
second uses agents/judge-second.toml, another model. --real calls Anthropic's API with the model in
the definition, and needs a credential the SDK can find: every call is billed, and the book hasn't
run it. Without --real, nothing here calls a model: the mock plays evals/judge-mock.json, whose
verdicts the lab chose, so its numbers test the machinery and never measure a model.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_policy import AGENTS, MODELS, POLICY, load, today
from agent_policy.rules import check as check_policy
from helpdesk import evals, patterns
from helpdesk.assistant.judging import (
    Agreement,
    Assessment,
    Criterion,
    Judgment,
    MalformedVerdict,
    Rubric,
    judge,
    load_rubric,
    read_verdict,
    revise_with_judge,
    second_slot,
)
from helpdesk.assistant.tools import triage_tools
from helpdesk.model.mock import MockModel
from helpdesk.model.stops import IncompleteResponse, final_text
from helpdesk.model.types import ModelClient, ModelResponse, ToolCall
from helpdesk.services import access, citations

EVALS = evals.EVALS
RUBRICS = EVALS / "rubrics"
LABELED = EVALS / "judged.json"
SCRIPTS = EVALS / "judge-mock.json"
JUDGES = {"same": AGENTS / "judge.toml", "second": AGENTS / "judge-second.toml"}
TRIALS = 3
# The second slot: the share of the replies a judge passed that a person reads anyway, drawn at
# random from a generator started at SEED, so the same run picks the same replies.
SHARE = 0.2
SEED = 22
MOCK = f"playing each label as its verdict except where evals/{SCRIPTS.name} scripts\nanother"


# --- Loading.


@dataclass(frozen=True)
class Labeled:
    id: str
    ticket: int
    reply: str
    person: dict[str, str]  # criterion to the person's label
    note: str
    given: tuple[str, ...]  # the tool results its writer was given


def labeled(path: Path = LABELED) -> tuple[Rubric, list[Labeled]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rubric = load_rubric(path.parent / data["rubric"])
    replies = [
        Labeled(
            r["id"], r["ticket"], r["reply"], r["person"], r["note"], tuple(data["given"][str(r["ticket"])])
        )
        for r in data["replies"]
    ]
    return rubric, replies


def scripts(path: Path = SCRIPTS) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def definition(which: str) -> dict[str, Any]:
    """A judge's definition, refused if it breaks the platform's policy."""
    path = JUDGES[which]
    found = load(path)
    problems = check_policy(found, load(POLICY), load(MODELS), today())
    if problems:
        detail = "; ".join(f"{p.path}: {p.reason}" for p in problems)
        raise SystemExit(f"agents/{path.name} breaks the platform's policy, so nothing ran: {detail}")
    return found


# --- The mock's answers.


def scripted(criterion: Criterion, play: Mapping[str, Any]) -> ModelResponse:
    """One scripted answer: a verdict the mock writes as JSON, raw text played as it is, or a stop."""
    if "stop" in play:
        return ModelResponse(play["stop"], text=play.get("raw", ""))
    if "raw" in play:
        return ModelResponse("end_turn", text=play["raw"])
    verdict = {"criterion": criterion.id, "verdict": play["verdict"], "reason": play["reason"]}
    if "quote" in play:
        verdict["quote"] = play["quote"]
    return ModelResponse("end_turn", text=json.dumps(verdict))


def plays_label(label: str) -> dict[str, str]:
    return {"verdict": label, "reason": "The mock's scripted verdict, the same as the person's label."}


class Counted:
    """Counts what the clients it wraps send, measured as the Anthropic adapter would send it."""

    def __init__(self) -> None:
        self.calls = 0
        self.chars = 0

    def wrap(self, inner: ModelClient) -> ModelClient:
        recorded = evals.Recorded(inner)
        counter = self

        class Client:
            def complete(self, **request: Any) -> ModelResponse:
                before = len(recorded.calls)
                try:
                    return recorded.complete(**request)
                finally:
                    for call in recorded.calls[before:]:
                        counter.calls += 1
                        counter.chars += patterns.request_size(call)

        return Client()


# --- Calibrating a judge against the person's labels.


@dataclass
class Calibration:
    rubric: Rubric
    replies: list[Labeled]
    trials: list[dict[str, Assessment]]  # one dict a trial: reply id to its assessment
    counted: Counted

    def agreement(self, criterion: str | None = None) -> Agreement:
        total = Agreement()
        for trial in self.trials:
            for reply in self.replies:
                for judgment in trial[reply.id].judgments:
                    if criterion is None or judgment.criterion == criterion:
                        total.add(judgment.outcome, reply.person[judgment.criterion])
        return total

    def matches(self, reply: Labeled, criterion: str) -> int:
        """Trials in which the judge gave the person's label."""
        return sum(t[reply.id].of(criterion).outcome == reply.person[criterion] for t in self.trials)


def calibrate(which: str, trials: int, real: bool, client: Any = None) -> Calibration:
    rubric, replies = labeled()
    found = definition(which)
    counted = Counted()
    plays = scripts()["calibrate"][which]
    shared = counted.wrap(evals.real_model(found, client)) if real else None
    results = []
    for _ in range(trials):
        by_reply = {}
        for reply in replies:

            def model_for(criterion: Criterion, reply: Labeled = reply) -> ModelClient:
                if shared is not None:
                    return shared
                label = plays_label(reply.person[criterion.id])
                play = plays.get(reply.id, {}).get(criterion.id, label)
                return counted.wrap(MockModel([scripted(criterion, play)]))

            by_reply[reply.id] = judge(model_for, found, rubric, reply.reply, reply.given)
        results.append(by_reply)
    return Calibration(rubric, replies, results, counted)


def model_line(real: bool, what: str) -> str:
    if real:
        return "Model: on Anthropic's API; every call was billed."
    return f"Model: the mock, {what}. The lab chose those, so these numbers test the machinery, not a model."


def rows_for(result: Calibration) -> list[tuple[str, ...]]:
    rows = [("criterion", "judged", "agree", "false pass", "false fail", "unknown", "errors")]
    for name in [c.id for c in result.rubric.criteria] + ["all"]:
        a = result.agreement(None if name == "all" else name)
        counts = (a.judged, a.agree, a.false_pass, a.false_fail, a.unknown, a.errors)
        rows.append((name, *map(str, counts)))
    return rows


def trials_of(result: Calibration, reply: Labeled, criterion: str) -> dict[str, list[int]]:
    """Each outcome the judge gave on one label, with the trials it gave it in."""
    seen: dict[str, list[int]] = {}
    for n, trial in enumerate(result.trials, 1):
        seen.setdefault(trial[reply.id].of(criterion).outcome, []).append(n)
    return seen


def disagreements(result: Calibration) -> list[str]:
    lines = []
    for reply in result.replies:
        for criterion in result.rubric.criteria:
            label = reply.person[criterion.id]
            for outcome, numbers in trials_of(result, reply, criterion.id).items():
                if outcome == label:
                    continue
                first = result.trials[numbers[0] - 1][reply.id].of(criterion.id)
                where = "trial" if len(numbers) == 1 else "trials"
                lines.append(
                    f"  {reply.id} {criterion.id}: the person says {label}, the judge {outcome} "
                    f"({where} {', '.join(map(str, numbers))}): {first.why}"
                )
    return lines


def consistent(result: Calibration) -> int:
    """Labels on which the judge gave the same outcome in every trial."""
    return sum(
        len(trials_of(result, reply, c.id)) == 1 for reply in result.replies for c in result.rubric.criteria
    )


def describe(which: str) -> str:
    return "the drafter's own model in a fresh context" if which == "same" else "a second model"


def run_calibrate(which: str, trials: int, real: bool) -> int:
    found = definition(which)
    result = calibrate(which, trials, real)
    labels = len(result.replies) * len(result.rubric.criteria)
    print(
        f"Labeled replies: evals/{LABELED.name}, {len(result.replies)} replies, "
        f"{len(result.rubric.criteria)} criteria (evals/rubrics/{result.rubric.id}.json). Trials: {trials}."
    )
    print(f"Judge: agents/{JUDGES[which].name}, {found['model']}, {describe(which)}, one criterion a call.")
    print(model_line(real, MOCK))
    print()
    print("\n".join(evals.table(rows_for(result), (False, True, True, True, True, True, True))))
    a = result.agreement()
    print()
    print(
        f"Agreement: {a.agree} of {a.judged} ({a.agree / a.judged:.0%}). A judge that passed everything "
        f"would agree on {a.person_passed} ({a.person_passed / a.judged:.0%})."
    )
    print(f"False passes, the judge passing what the person failed: {a.false_pass}.")
    print(f"Consistency: the same verdict in every trial on {consistent(result)} of {labels} labels.")
    print(f"Tokens sent (est.): {evals.tokens(result.counted.chars):,} in {result.counted.calls} calls.")
    lost = disagreements(result)
    if lost:
        print("\nDisagreements with the person:")
        print("\n".join(lost))
    outcomes = {r.id: result.trials[0][r.id].outcome for r in result.replies}
    slot = second_slot(outcomes, share=SHARE, seed=SEED)
    listed = ", ".join(f"{i} ({why})" for i, why in slot) or "nothing"
    print(f"\nWith nobody's labels, a person would read: {listed}.")
    return 0


def run_compare(trials: int, real: bool) -> int:
    results = {which: calibrate(which, trials, real) for which in JUDGES}
    first = results["same"]
    print(
        f"Labeled replies: evals/{LABELED.name}, {len(first.replies)} replies, "
        f"{len(first.replies) * len(first.rubric.criteria)} labels. Trials: {trials} a judge."
    )
    print(model_line(real, MOCK))
    print()
    rows = [("judge", "model", "agree", "false pass", "false fail", "unknown", "errors", "tokens (est.)")]
    for which, result in results.items():
        a = result.agreement()
        counts = (a.false_pass, a.false_fail, a.unknown, a.errors)
        sent = f"{evals.tokens(result.counted.chars):,}"
        rows.append((which, definition(which)["model"], f"{a.agree} of {a.judged}", *map(str, counts), sent))
    print("\n".join(evals.table(rows, (False, False, True, True, True, True, True, True))))
    a = first.agreement()
    print(f"A judge that passed everything would agree on {a.person_passed} of {a.judged}.")
    better = {"same": 0, "second": 0, "tie": 0}
    for reply in first.replies:
        for c in first.rubric.criteria:
            s, t = results["same"].matches(reply, c.id), results["second"].matches(reply, c.id)
            better["same" if s > t else "second" if t > s else "tie"] += 1
    print(
        f"\nPaired by label: the same model matched the person more often on {better['same']}, the second "
        f"model on {better['second']}, and they tied on {better['tie']}."
    )
    for which, result in results.items():
        lost = disagreements(result)
        if lost:
            print(f"\nWhere the {which} judge disagreed with the person:")
            print("\n".join(lost))
    return 0


# --- The judge as evaluator.


def revise_script(play: Mapping[str, Any]) -> list[ModelResponse]:
    """The drafter as the mock plays it: the first round's tool calls, then one draft a round."""
    script = [
        ModelResponse(
            "tool_use",
            tool_calls=tuple(
                ToolCall(f"d{n}_{i}", name, dict(args)) for i, (name, args) in enumerate(turn, 1)
            ),
        )
        for n, turn in enumerate(play["turns"], 1)
    ]
    return [*script, *(ModelResponse("end_turn", text=draft) for draft in play["drafts"])]


def verdict_lines(judgments: tuple[Judgment, ...]) -> list[str]:
    """The criteria that passed on one line, then each one that didn't, with the judge's reason."""
    passed = [j.criterion for j in judgments if j.outcome == "pass"]
    lines = [f"Judge: {', '.join(passed) or 'nothing'} pass."]
    return lines + [f"  {j.criterion}: {j.outcome}. {j.why}" for j in judgments if j.outcome != "pass"]


def run_revise(which: str, max_rounds: int, real: bool) -> int:
    found = definition(which)
    triage = evals.triage_definition()
    rubric = load_rubric(RUBRICS / "reply.json")
    play = scripts()["revise"]
    drafter_count, judge_count = Counted(), Counted()
    if real:
        drafter = drafter_count.wrap(evals.real_model(triage))
        shared = judge_count.wrap(evals.real_model(found))

        def judge_for(round_number: int, criterion: Criterion) -> ModelClient:
            return shared

        line = "Drafter and judge: on Anthropic's API; every call below is billed."
    else:
        drafter = drafter_count.wrap(MockModel(revise_script(play)))

        def judge_for(round_number: int, criterion: Criterion) -> ModelClient:
            verdicts = play["verdicts"]
            chosen = verdicts[min(round_number, len(verdicts)) - 1].get(criterion.id, plays_label("pass"))
            return judge_count.wrap(MockModel([scripted(criterion, chosen)]))

        line = "Drafter and judge: the mock, scripted so the judge never passes every criterion."
    with evals.helpdesk() as (conn, _):
        person = access.find_person(conn, "sam")
        tools = triage_tools(conn, person).only(["get_ticket", "search_kb"])
        print(f"Task: {play['task']}\n{line}")
        print(f"Judge: agents/{JUDGES[which].name}. Acting for: {person.label}\n")
        result = revise_with_judge(
            drafter,
            tools,
            judge_for,
            found,
            rubric,
            system=triage["system"],
            task=play["task"],
            known=evals.known_passages(conn),
            max_rounds=max_rounds,
        )
    for r in result.rounds:
        print(f"Round {r.number}, draft:\n{patterns.indented(r.draft)}")
        if r.assessment is None:
            print(f"Citations: {len(r.report.problems)} problem(s), so the judge wasn't asked.")
        else:
            print("Citations: hold. " + "\n".join(verdict_lines(r.assessment.judgments)))
        if r is not result.rounds[-1]:
            print("Sent back to the drafter with the reasons.")
        print()
    sent = (
        f"{drafter_count.calls} requests to the drafter and {judge_count.calls} to the judge, "
        f"{evals.tokens(drafter_count.chars + judge_count.chars):,} tokens sent (est.)."
    )
    rounds = f"{len(result.rounds)} round{'s' if len(result.rounds) > 1 else ''} (limit {max_rounds})"
    if result.accepted:
        print(f"Accepted after {rounds}. {sent}")
        return 0
    why = {
        "limit": "the judge still fails the draft",
        "person": "the judge couldn't settle a criterion",
        "unchanged": "the draft came back unchanged, so another round wouldn't help",
    }[result.stopped]
    print(f"Stopped after {rounds}: {why}. {sent}")
    print("A person reads this draft, and the judge's last reasons, before anything is sent.")
    return 1


# --- A document.


def run_doc(path: Path, which: str, real: bool) -> int:
    found = definition(which)
    rubric = load_rubric(RUBRICS / "instructions.json")
    text = path.read_text(encoding="utf-8")
    counted = Counted()
    play = scripts()["doc"]
    shared = counted.wrap(evals.real_model(found)) if real else None

    def model_for(criterion: Criterion) -> ModelClient:
        if shared is not None:
            return shared
        return counted.wrap(MockModel([scripted(criterion, play)]))

    print(f"Document: {path.as_posix()} ({len(text):,} characters). Rubric: evals/rubrics/{rubric.id}.json.")
    what = "on Anthropic's API; every call is billed" if real else "the mock, which plays unknown for it"
    print(f"Judge: agents/{JUDGES[which].name}, {found['model']}. Model: {what}.\n")
    assessment = judge(model_for, found, rubric, text, ())
    width = max(len(c.id) for c in rubric.criteria)
    for j in assessment.judgments:
        print(f"{j.criterion.ljust(width)}  {j.outcome}: {j.why}")
    unsettled = sum(j.outcome in ("unknown", "error") for j in assessment.judgments)
    outcome = {
        "pass": "every criterion passes",
        "fail": "it fails at least one criterion",
        "person": f"a person reads it ({unsettled} criteria the judge couldn't settle)",
    }[assessment.outcome]
    print(f"\nOutcome: {outcome}.")
    print(f"Tokens sent (est.): {evals.tokens(counted.chars):,} in {counted.calls} calls.")
    return 0 if assessment.outcome == "pass" else 1


# --- Checking the judge's inputs, and that its verdicts can fail.

GOOD = {"criterion": "answers", "verdict": "pass", "reason": "It explains where the export is."}


def answer(text: str, stop: str = "end_turn") -> ModelResponse:
    return ModelResponse(stop, text=text)  # type: ignore[arg-type]


def verdict_with(**changes: Any) -> str:
    return json.dumps({**GOOD, **changes})


# Answers a judge might give that must never count. Each must be refused, and none is a pass.
MALFORMED: tuple[tuple[str, ModelResponse], ...] = (
    ("prose, not JSON", answer("Pass. The reply answers the question.")),
    ("JSON in a code fence", answer("```json\n" + json.dumps(GOOD) + "\n```")),
    ("JSON with words after it", answer(json.dumps(GOOD) + " I hope this helps.")),
    ("a field the schema doesn't have", answer(verdict_with(score=4))),
    ("no reason", answer(json.dumps({"criterion": "answers", "verdict": "pass"}))),
    ("an empty reason", answer(verdict_with(reason="  "))),
    ("a verdict outside pass, fail and unknown", answer(verdict_with(verdict="partial"))),
    ("true for pass", answer(verdict_with(verdict=True))),
    ("the wrong criterion", answer(verdict_with(criterion="tone"))),
    ("a quote the text doesn't contain", answer(verdict_with(quote="we'll refund you"))),
    (
        "a verdict given twice, fail then pass",
        answer(verdict_with(verdict="fail")[:-1] + ', "verdict": "pass"}'),
    ),
    ("a refusal", answer(json.dumps(GOOD), "refusal")),
    ("an answer cut off at max_tokens", answer(json.dumps(GOOD)[:30], "max_tokens")),
)


def refused(response: ModelResponse, criterion: Criterion, text: str) -> bool:
    """Whether the judge's code refuses this answer, reading it as judge_one does."""
    try:
        read_verdict(final_text(response), criterion, text)
    except (MalformedVerdict, IncompleteResponse):
        return True
    return False


def check_rubrics(problems: list[str]) -> None:
    rubrics = []
    for path in sorted(RUBRICS.glob("*.json")):
        try:
            rubrics.append(load_rubric(path))
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            problems.append(f"rubrics/{path.name}: {error}")
    if len(rubrics) == len(list(RUBRICS.glob("*.json"))):
        count = sum(len(r.criteria) for r in rubrics)
        print(f"evals/rubrics: {len(rubrics)} rubrics, {count} criteria, every one well-formed.")


def check_labels(rubric: Rubric, replies: list[Labeled], problems: list[str]) -> int:
    """The labeled set: every criterion labeled pass or fail on every reply, every criterion with a
    pass and a fail, and every reply's citations holding. Returns how many labels are fails."""
    before = len(problems)
    ids = sorted(c.id for c in rubric.criteria)
    fails = 0
    for reply in replies:
        where = f"judged.json: {reply.id}"
        if sorted(reply.person) != ids:
            have = ", ".join(sorted(reply.person))
            problems.append(f"{where}: labels {have}, where the rubric has {', '.join(ids)}.")
            continue
        unsure = sorted(k for k, v in reply.person.items() if v not in ("pass", "fail"))
        if unsure:
            problems.append(
                f"{where}: label {', '.join(unsure)} pass or fail; an unsure label calibrates nothing."
            )
        fails += sum(v == "fail" for v in reply.person.values())
        given: dict[str, str] = {}
        for text in reply.given:
            given |= citations.passages_in(text)
        for problem in citations.check(reply.reply, given).problems:
            problems.append(f"{where}: {problem.reason}. Code catches that; this set is for what it can't.")
    for c in ids:
        seen = {r.person.get(c) for r in replies}
        if not {"pass", "fail"} <= seen:
            problems.append(
                f"judged.json: {c} needs a reply the person passed and one they failed, or agreement on it "
                "can't tell a judge from one that always gives the same answer."
            )
    if len(problems) == before:
        labels = len(replies) * len(ids)
        print(
            f"evals/judged.json: {len(replies)} replies, {labels} labels ({fails} fail): every criterion has "
            "a pass and a fail,\nand every reply's citations hold, so only judgment tells them apart."
        )
    return fails


def check_scripts(rubric: Rubric, replies: list[Labeled], problems: list[str]) -> None:
    before = len(problems)
    known, ids = {r.id for r in replies}, {c.id for c in rubric.criteria}
    for which, by_reply in scripts()["calibrate"].items():
        if which not in JUDGES:
            problems.append(f"judge-mock.json: {which} isn't a judge; the judges are {', '.join(JUDGES)}.")
        for reply_id, by_criterion in by_reply.items():
            for c in by_criterion:
                if reply_id not in known or c not in ids:
                    problems.append(f"judge-mock.json: {which} scripts {reply_id} {c}, which isn't labeled.")
    if len(problems) == before:
        print(f"evals/{SCRIPTS.name}: every scripted verdict names a reply and a criterion that exist.")


def check_verdicts(rubric: Rubric, replies: list[Labeled], problems: list[str]) -> None:
    before = len(problems)
    criterion, text = rubric.criteria[0], replies[0].reply
    for label, response in MALFORMED:
        if not refused(response, criterion, text):
            problems.append(f"verdicts: the malformed answer '{label}' is accepted as a verdict.")
    if refused(answer(json.dumps(GOOD)), criterion, text):
        problems.append("verdicts: a well-formed verdict is refused, so every verdict would be an error.")
    if len(problems) == before:
        print(
            f"Verdicts: every one of {len(MALFORMED)} malformed answers is refused, never counted as a pass."
        )


def check_agreement(replies: list[Labeled], fails: int, problems: list[str]) -> None:
    copier, stamp = Agreement(), Agreement()
    for reply in replies:
        for label in reply.person.values():
            copier.add(label, label)
            stamp.add("pass", label)
    if copier.agree != copier.judged or stamp.false_pass != fails or stamp.agree == stamp.judged:
        problems.append(
            "agreement: the counts can't tell a judge that copies the labels from a rubber stamp."
        )
        return
    print(
        f"A judge that copies the labels agrees on {copier.agree} of {copier.judged}; one that passes "
        f"everything agrees on {stamp.agree}\nand passes all {stamp.false_pass} fails."
    )


def check_all() -> int:
    problems: list[str] = []
    check_rubrics(problems)
    rubric, replies = labeled()
    fails = check_labels(rubric, replies, problems)
    check_scripts(rubric, replies, problems)
    check_verdicts(rubric, replies, problems)
    check_agreement(replies, fails, problems)
    if problems:
        print("\n" + "\n".join(problems))
        return 1
    print("Every verdict is checked before it counts, and the labels can tell a judge from a rubber stamp.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.judge")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="the judge's inputs are sound, and its verdicts can fail")
    for name in ("calibrate", "compare", "revise", "doc"):
        command = commands.add_parser(name)
        command.add_argument("--real", action="store_true", help="call Anthropic's API; every call is billed")
        if name != "compare":
            command.add_argument("--judge", choices=list(JUDGES), default="same", help="which judge")
        if name in ("calibrate", "compare"):
            command.add_argument(
                "--trials", type=int, default=TRIALS, help=f"runs a label (default {TRIALS})"
            )
        if name == "revise":
            command.add_argument("--max-rounds", type=int, default=3, help="drafts before a person decides")
        if name == "doc":
            command.add_argument("path", type=Path, help="the instruction file to judge")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check_all()
    if getattr(args, "trials", 1) < 1:
        parser.error("--trials must be 1 or more")
    if getattr(args, "max_rounds", 1) < 1:
        parser.error("--max-rounds must be 1 or more")
    if args.real:
        print("Calling Anthropic's API: every call below is a billed run.\n")
    if args.command == "calibrate":
        return run_calibrate(args.judge, args.trials, args.real)
    if args.command == "compare":
        return run_compare(args.trials, args.real)
    if args.command == "revise":
        return run_revise(args.judge, args.max_rounds, args.real)
    return run_doc(args.path, args.judge, args.real)


if __name__ == "__main__":
    sys.exit(main())
