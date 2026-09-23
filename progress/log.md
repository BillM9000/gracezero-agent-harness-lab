# Session log

What each working session did, newest first. Add an entry at the end of every session: what changed, how you checked it, and what the next session should do first. Name the command behind each claim, so the next session can run it again instead of trusting the sentence.

## 2026-09-23: chapter 15, fitness functions

- Added `python/tests/fitness/`: two checks that walk the syntax tree (every route declares a response model; no test builds the real model client without a fake) and one that runs the whole app (no read route returns a customer's email). Each has tests that plant a violation. 11 tests.
- Broke each on purpose: removing a response model, building the real client in a test, and putting an email into the sample data each failed a fitness test; so did breaking each rule's own logic, once a missing case (stale exemptions) had a test.
- Work list: `fitness-functions` added as done, with its proof.
- Checked with: `node check.mjs` (all 13 checks passed) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 10, the work list and this log

- Added `progress/features.json`, the lab's work list in priority order: 6 items done, each naming the test that proves it, and 5 to do.
- Added `tools/progress.mjs`, which shows what's next and fails when a done item names no test that exists or when more than one item is in progress. 8 tests. `node check.mjs` runs it as its 13th check.
- `AGENTS.md` now opens with how to start a session. Its check count had to change from 12 to 13, and `node check.mjs` failed until it did.
- Checked with: `node check.mjs` (all 13 checks passed) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, the first item to do.
