# Session log

What each working session did, newest first. Add an entry at the end of every session: what changed, how you checked it, and what the next session should do first. Name the command behind each claim, so the next session can run it again instead of trusting the sentence.

## 2026-09-23: chapter 24, checks in tiers

- `node check.mjs --fast` skips the test suites; `node tools/mutate.mjs` breaks every listed guard and requires a test to catch it (56 entries); CI split into `ci.yml` (code), `docs.yml` (Markdown alone) and `nightly.yml` (mutations).
- The runner's tests found that a nested `node --test` runs none of its test files and exits 0 under an inherited `NODE_TEST_CONTEXT`; the runner now removes it. (First written as "exits 0"; running it with its output shown found it skips the files, with a warning.)
- Work list: `guard-mutations` added as done, with its proof.
- Checked with: `node check.mjs` (all 17 checks passed), `node tools/mutate.mjs` (all 56 caught, from a fresh clone) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 18, agent definitions and their policy

- The triage assistant's settings moved from `helpdesk/triage.py` into `agents/triage.toml`; `python -m agent_policy` checks every definition against `agents/policy.toml`, and the assistant refuses to run one that fails. 16 fixtures specify the rules; 26 tests.
- Broke each guard in turn (17 changes); a test failed each time, once the one badly written change was fixed.
- Work list: `agent-policy` added as done, with its proof.
- Checked with: `node check.mjs` (all 17 checks passed) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 17, custom lint rules

- Python: `python -m helpdesk_lint` enforces AGENTS.md rule 5 (a model's text through `final_text`). Its first run flagged `assistant/agent.py`'s transcript line, which is correct, so it carries a `# HDK101:` exception with its reason. 10 tests.
- TypeScript: a custom ESLint rule sends output through `write` in functions that take it, with a fix for `console.log` and a suggestion for the rest. 8 tests.
- Broke each guard in turn (18 changes); a test failed each time.
- Work list: `model-text-rule` and `cli-output-rule` added as done, with their proofs.
- Checked with: `node check.mjs` (all 16 checks passed) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 16, boundary rules

- Python: a fourth import contract keeps the `anthropic` SDK inside `helpdesk.model` (an allow-list, so new modules are covered), and each contract's fix is now in `broken_contract_guidance`. 2 new guardrail tests.
- TypeScript: ESLint (`npm run lint`) and dependency-cruiser (`npm run deps`) enforce the package's import rules; `ts/test/boundaries.test.ts` plants a violation for each and checks that both tools read every file. TypeScript 6's API now sits beside TypeScript 7 for these tools.
- `boundaries/`: the same layer rule in Go, Java and .NET. Not run: only CI can run them, and it hasn't.
- Broke each guard in turn (20 changes); a test failed each time.
- Work list: `model-sdk-in-one-package` and `typescript-import-rules` added as done, with their proofs.
- Checked with: `node check.mjs` (all 15 checks passed) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

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
