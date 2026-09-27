"""Evaluations as a gate (chapter 23): which differences between the last promotion and this run
are regressions, and which are noise. Pure functions; python -m helpdesk.gate runs the golden sets
and the judge, keeps the record, and calls these.

Three rules, each for a different way a change can hurt:

- A suite that allows no failure (the red-team tickets): any failed trial fails the gate.
- A case that passed every trial at the last promotion is a regression case (Anthropic's post calls
  such tasks a regression suite, with a nearly 100% pass rate). It fails the gate when it fails more
  trials than chance explains: the fewest failures that a case still passing at the expected rate
  would reach by chance no more often than the false-alarm rate.
- A whole suite, over the cases that passed every trial at promotion: a small drop spread over many
  cases, which no one case shows, fails the gate when their failed trials, added up, reach the
  fewest that cases still passing at the expected rate would reach by chance no more often than the
  false-alarm rate. Their failures add up to one binomial count, so the threshold is computed
  exactly, the same way as the per-case one. It's used only on suites with enough such cases.

Each rule holds its own false alarms to the rate; a healthy suite can trip either, so the chance it
fails the gate is a little more than either alone. suite_fails_gate computes it exactly, for cases
passing at any rate: at the expected rate it's the false alarm (healthy_suite_fails), and below it,
how often the gate catches the drop. python -m helpdesk.gate check prints both, counting both rules.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from math import comb

Counts = tuple[int, int]  # (passed, trials)


def chance_of_at_least(failures: int, trials: int, fail_rate: float) -> float:
    """The chance of `failures` or more failed trials out of `trials`, each failing independently
    at `fail_rate`."""
    return sum(
        comb(trials, k) * fail_rate**k * (1 - fail_rate) ** (trials - k) for k in range(failures, trials + 1)
    )


def failures_to_fail(trials: int, expected: float, false_alarm: float) -> int | None:
    """The fewest failed trials, out of `trials`, that fail a regression case (or a suite's
    regression cases, their trials added up): the smallest count trials still passing at `expected`
    reach by chance no more often than `false_alarm`. None when no count is that unlikely, so the
    gate could never fail a case: run more trials."""
    for failures in range(1, trials + 1):
        if chance_of_at_least(failures, trials, 1 - expected) <= false_alarm:
            return failures
    return None


@dataclass(frozen=True)
class Rule:
    trials: int
    expected: float  # how often a regression case is assumed to pass while nothing is wrong
    false_alarm: float  # the most often each rule may fail a healthy case, or suite, by chance
    every_trial: frozenset[str]  # suites that allow no failed trial
    suite_min_cases: int  # the fewest cases that passed every trial the suite rule is used on

    def __post_init__(self) -> None:
        problems = []
        if self.trials < 1:
            problems.append("trials must be 1 or more")
        if not 0 < self.expected < 1:
            problems.append("expected_pass_rate must be between 0 and 1")
        if not 0 < self.false_alarm < 0.5:
            problems.append("false_alarm must be between 0 and 0.5")
        if self.suite_min_cases < 2:
            problems.append("suite_min_cases must be 2 or more: on one case, the suite rule is the case rule")
        if problems:
            raise ValueError("; ".join(problems))

    @property
    def fails_at(self) -> int | None:
        return failures_to_fail(self.trials, self.expected, self.false_alarm)

    def suite_fails_at(self, cases: int) -> int | None:
        """The fewest failed trials, added up over `cases` regression cases, that fail a suite."""
        return failures_to_fail(cases * self.trials, self.expected, self.false_alarm)


def suite_fails_gate(cases: int, rule: Rule, pass_rate: float) -> float:
    """The chance that `cases` regression cases, each now passing at `pass_rate`, fail the gate: one
    case reaching the case rule's count, or all of them the suite rule's. Exact, over every total of
    failures the cases can have without any one reaching the case rule."""
    fail_rate = 1 - pass_rate
    one = [
        comb(rule.trials, k) * fail_rate**k * (1 - fail_rate) ** (rule.trials - k)
        for k in range(rule.trials + 1)
    ]
    case_at = rule.fails_at if rule.fails_at is not None else rule.trials + 1
    suite_at = rule.suite_fails_at(cases) if cases >= rule.suite_min_cases else None
    totals = {0: 1.0}  # chance of each total so far, with no case at the case rule's count
    for _ in range(cases):
        grown: dict[int, float] = {}
        for so_far, chance in totals.items():
            for k in range(case_at):
                grown[so_far + k] = grown.get(so_far + k, 0.0) + chance * one[k]
        totals = grown
    passes = sum(chance for total, chance in totals.items() if suite_at is None or total < suite_at)
    return 1 - passes


def healthy_suite_fails(cases: int, rule: Rule) -> float:
    """The chance that `cases` regression cases, each still passing at the expected rate, fail the
    gate by chance, by either rule: its false alarm."""
    return suite_fails_gate(cases, rule, rule.expected)


@dataclass
class Verdict:
    """What one part of the gate found: failures fail the gate; notes are reported and don't."""

    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def judge_suite(suite: str, before: Mapping[str, Counts], after: Mapping[str, Counts], rule: Rule) -> Verdict:
    """Compare one suite's run with the record, case by case and as a whole."""
    verdict = Verdict()
    fails_at = rule.fails_at
    if not before and suite not in rule.every_trial:
        verdict.notes.append("nothing in the record to compare with: this run is the baseline")
    for case, (passed, trials) in after.items():
        failed = trials - passed
        if suite in rule.every_trial:
            if failed:
                verdict.failures.append(f"{case}: failed {failed} of {trials}; this suite allows no failure")
            continue
        if not before:
            continue
        if case not in before:
            verdict.notes.append(f"{case}: no count in the record, so it can't regress yet")
            continue
        was_passed, was_trials = before[case]
        if was_passed < was_trials:
            if failed:
                verdict.notes.append(
                    f"{case}: failed {failed} of {trials}; it failed {was_trials - was_passed} of "
                    f"{was_trials} at promotion, so it doesn't gate"
                )
            continue
        if fails_at is not None and failed >= fails_at:
            verdict.failures.append(
                f"{case}: failed {failed} of {trials}; it passed every trial at promotion, and "
                f"{fails_at} failures are more than chance explains"
            )
        elif failed:
            verdict.notes.append(
                f"{case}: failed {failed} of {trials}, within noise (the gate fails it at {fails_at})"
            )
    regression = [case for case in after if case in before and before[case][0] == before[case][1]]
    if suite not in rule.every_trial and len(regression) >= rule.suite_min_cases:
        failed = sum(after[case][1] - after[case][0] for case in regression)
        trials = sum(after[case][1] for case in regression)
        suite_at = failures_to_fail(trials, rule.expected, rule.false_alarm)
        who = f"the {len(regression)} cases that passed every trial at promotion"
        if suite_at is not None and failed >= suite_at:
            by_chance = chance_of_at_least(suite_at, trials, 1 - rule.expected)
            verdict.failures.append(
                f"{who}: failed {failed} of {trials}; {suite_at} or more is more than chance explains "
                f"(cases still passing {rule.expected:.0%} of the time reach it {by_chance:.1%} of the time)"
            )
        elif failed:
            verdict.notes.append(
                f"{who}: failed {failed} of {trials}, within noise (the gate fails the suite at {suite_at})"
            )
    return verdict


def held_false_passes(false_passes: Mapping[str, int], trials: int) -> set[str]:
    """Labels the judge passed, where the person failed them, in most of its trials."""
    return {label for label, count in false_passes.items() if count * 2 > trials}


def judge_calibration(
    before: Collection[str] | None, held: Collection[str], agree: int, rubber_stamp: int, judged: int
) -> Verdict:
    """The judge gates too: no false pass it holds that it didn't hold at promotion, and agreement
    above what a judge that passed everything would score. With no record (before is None), this run
    is the baseline, and the false passes it holds are reported for a person to read."""
    verdict = Verdict()
    known = set(before or ())
    for label in sorted(set(held) - known):
        if before is None:
            verdict.notes.append(f"{label}: a false pass the judge gives in most trials (no record yet)")
        else:
            verdict.failures.append(
                f"{label}: a false pass the judge gives in most trials, new since promotion"
            )
    for label in sorted(set(held) & known):
        verdict.notes.append(f"{label}: a false pass it gave at promotion too")
    if agree <= rubber_stamp:
        verdict.failures.append(
            f"it agrees with the person on {agree} of {judged}, "
            f"no better than passing everything ({rubber_stamp})"
        )
    return verdict
