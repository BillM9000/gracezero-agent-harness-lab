# Session log

What each working session did, newest first. Add an entry at the end of every session: what changed, how you checked it, and what the next session should do first. Name the command behind each claim, so the next session can run it again instead of trusting the sentence.

## 2026-09-27: what the mutation counts below mean

- The mutation-entry counts recorded in the entries below predate the review fixes of 27 September 2026 and the fixes of 30 September 2026. This history places those fixes, and their mutation entries, before the chapter tags, so the list at a tag can hold more entries than the log entry beside it records. Count the list at a tag by importing that tag's copy of `tools/mutations.mjs`, which `git show chNN:tools/mutations.mjs` prints, and reading the length of its `MUTATIONS`. Trust the count, not a number here.

## 2026-09-23: chapter 9, retrieval over the knowledge base

- `search_kb` returns ranked passages (keyword and vector rankings fused by rank) with ids to cite, and the triage assistant's answers have their citations checked against what the run was given. `python -m helpdesk.kb eval` measures recall at 3 on `python/evals/kb_questions.json` and is the 18th check. 39 new Python tests.
- Measured on the golden set: hybrid 21 of 24, keyword and vector 20 each; 3 of 3 questions with no answer got nothing.
- Broke each new guard in turn (13 new entries in `tools/mutations.mjs`); a test failed each time.
- Work list: `kb-retrieval` added as done, with its proof.
- Checked with: `node check.mjs` (all 18 checks passed), `node tools/mutate.mjs` (all 93 caught, from a fresh clone) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 31, where agent work gets redone

- `node tools/rework.mjs` counts, from git history alone, where fixes landed on recent agent work, by folder, with the median time to the fix; `node tools/rework-demo.mjs` builds a history to try it on. 10 new script tests.
- Its first run on a real repository counted bookkeeping as rework (a changelog, a version number), so Markdown is now left out by default and `--ignore` leaves out more.
- Broke each new guard in turn (10 new entries in `tools/mutations.mjs`); a test failed each time.
- Work list: `rework-count` added as done, with its proof.
- Checked with: `node check.mjs` (all 17 checks passed), `node tools/mutate.mjs` (all 80 caught, from a fresh clone) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 25, closing the loop

- A Stop hook (`tools/hooks/stop-check.mjs`, wired up in `.claude/settings.json`) runs `node check.mjs --fast` when the agent stops and sends a failure back, at most three rounds in a row. `tools/fix-loop.mjs` does the same for a pipeline, with any agent command; `tools/stand-in-agent.mjs` stands in for one. 22 new script tests.
- Broke each new guard in turn (14 new entries in `tools/mutations.mjs`); a test failed each time.
- Work list: `stop-hook` and `fix-loop` added as done, with their proofs.
- Not run with a live agent: the hook follows Claude Code's documented input and output, and its tests feed it that input.
- Checked with: `node check.mjs` (all 17 checks passed), `node tools/mutate.mjs` (all 70 caught, from a fresh clone) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

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
