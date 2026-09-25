"""Evaluations as a gate (chapter 23): which differences between the last promotion and this run
are regressions, and which are noise. Pure functions; python -m helpdesk.gate runs the golden sets
and the judge, keeps the record, and calls these.

Three rules, each for a different way a change can hurt:

- A suite that allows no failure (the red-team tickets): any failed trial fails the gate.
- A case that passed every trial at the last promotion is a regression case (Anthropic's post calls
  such tasks a regression suite, with a nearly 100% pass rate). It fails the gate when it fails more
  trials than chance explains: the fewest failures that a case still passing at the expected rate
  would reach by chance no more often than the false-alarm rate.
- A whole suite, paired case by case against the record (Miller's paired differences, a 95%
  interval): a small drop spread over many cases, which no one case shows, fails the gate when the
  whole interval is below zero. The interval rests on the normal approximation, so it's used only
  on suites with enough cases.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from math import comb, sqrt

# A 95% interval under the normal approximation (Miller, "Adding Error Bars to Evals", 2024).
Z_95 = 1.96

Counts = tuple[int, int]  # (passed, trials)


def chance_of_at_least(failures: int, trials: int, fail_rate: float) -> float:
    """The chance of `failures` or more failed trials out of `trials`, each failing independently
    at `fail_rate`."""
    return sum(
        comb(trials, k) * fail_rate**k * (1 - fail_rate) ** (trials - k) for k in range(failures, trials + 1)
    )


def failures_to_fail(trials: int, expected: float, false_alarm: float) -> int | None:
    """The fewest failed trials that fail a regression case: the smallest count a case still
    passing at `expected` reaches by chance no more often than `false_alarm`. None when no count
    is that unlikely, so the gate could never fail a case: run more trials."""
    for failures in range(1, trials + 1):
        if chance_of_at_least(failures, trials, 1 - expected) <= false_alarm:
            return failures
    return None


@dataclass(frozen=True)
class Rule:
    trials: int
    expected: float  # how often a regression case is assumed to pass while nothing is wrong
    false_alarm: float  # the most often such a case may fail the gate by chance
    every_trial: frozenset[str]  # suites that allow no failed trial
    paired_min_cases: int  # the fewest cases the paired interval is used on

    def __post_init__(self) -> None:
        problems = []
        if self.trials < 1:
            problems.append("trials must be 1 or more")
        if not 0 < self.expected < 1:
            problems.append("expected_pass_rate must be between 0 and 1")
        if not 0 < self.false_alarm < 0.5:
            problems.append("false_alarm must be between 0 and 0.5")
        if self.paired_min_cases < 2:
            problems.append("paired_min_cases must be 2 or more: one case has no spread to measure")
        if problems:
            raise ValueError("; ".join(problems))

    @property
    def fails_at(self) -> int | None:
        return failures_to_fail(self.trials, self.expected, self.false_alarm)


@dataclass(frozen=True)
class Change:
    """The mean change in pass rate, run minus record, paired by case, with its 95% interval."""

    mean: float
    low: float
    high: float

    @property
    def beyond_noise(self) -> bool:
        return self.high < 0


def paired_change(before: Sequence[float], after: Sequence[float]) -> Change:
    """Miller's paired difference: the mean of each case's change, and a standard error from the
    spread of those changes, so what the two runs share doesn't count as noise."""
    if len(before) != len(after) or len(before) < 2:
        raise ValueError("a paired change needs the same cases in both runs, at least two")
    diffs = [a - b for b, a in zip(before, after, strict=True)]
    mean = sum(diffs) / len(diffs)
    spread = sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)
    error = sqrt(spread / len(diffs))
    return Change(mean, mean - Z_95 * error, mean + Z_95 * error)


@dataclass
class Verdict:
    """What one part of the gate found: failures fail the gate; notes are reported and don't."""

    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def rate(counts: Counts) -> float:
    return counts[0] / counts[1]


def points(share: float) -> int:
    """A change in pass rate in percentage points, rounded."""
    return round(share * 100)


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
    common = [case for case in after if case in before]
    if suite not in rule.every_trial and len(common) >= rule.paired_min_cases:
        change = paired_change([rate(before[c]) for c in common], [rate(after[c]) for c in common])
        fell, span = points(-change.mean), f"{points(change.low):+d} to {points(change.high):+d} points"
        if change.beyond_noise:
            verdict.failures.append(
                f"down {fell} points over {len(common)} cases, paired by case (95% interval {span}): "
                "more than noise"
            )
        elif change.mean < 0:
            verdict.notes.append(
                f"down {fell} points over {len(common)} cases, paired by case (95% interval {span}): "
                "within noise"
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
