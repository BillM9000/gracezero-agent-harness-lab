# Session log

What each working session did, newest first. Add an entry at the end of every session: what changed, how you checked it, and what the next session should do first. Name the command behind each claim, so the next session can run it again instead of trusting the sentence.

## 2026-09-27: what the mutation counts below mean

- The mutation-entry counts recorded in the entries below predate the review fixes of 27 September 2026 and the fixes of 30 September 2026. This history places those fixes, and their mutation entries, before the chapter tags, so the list at a tag can hold more entries than the log entry beside it records. Count the list at a tag by importing that tag's copy of `tools/mutations.mjs`, which `git show chNN:tools/mutations.mjs` prints, and reading the length of its `MUTATIONS`; on the working tree, `node tools/mutate.mjs --list` prints every entry and the total. Trust the count, not a number here.

## 2026-09-25: chapter 29, rolling it out to teams

- `python/golden-path/`: the golden path's `template.toml` (the model, limits and read-only tools it gives, the intake answers, what it leaves to the team, the platform's standard text, the golden state's three checks, and example answers) and the two files it writes, `agent.tmpl` and `usecase.tmpl`.
- `src/golden_path/rules.py`: the answers' rules, rendering (every answer written as a TOML string, the prompt wrapped the way `agents/triage.toml` is), and the golden state as pure functions. `python -m helpdesk.golden_path` (a composition root): `new NAME` writes only once what it would write passes; `check` is the 26th check; `report` shows adoption team by team.
- Readiness exceptions (`src/readiness/rules.py`, `usecases/readiness.toml`): a reviewer, never the champion, may excuse the library, servers, promotion or red-team item for up to 30 days, with a reason; an ended one fails, and so does one with nothing left to excuse. `python -m helpdesk.readiness check --today` judges them as of a day. The fingerprint leaves exceptions out.
- 45 new Python tests (643); 30 new mutation entries and one updated (448), all applied and caught on the working tree before commit.
- Work list: `rollout-to-teams` done, proved by `tests/test_golden_path.py`. No next item added: no written chapter asks for one yet.
- Checked with: `node check.mjs` (all 26 checks passed) and `node tools/progress.mjs .`.
- Not run: `--real`, for any command; nothing here calls a model.
- Then `node tools/mutate.mjs` on the committed tree at `c64331e`: all 448 caught in 20.7 minutes, and the tree unchanged.
- Then the promotion item's message: "something the promotion of DATE measured has changed since", not "what the model is given changed", since the judge's rubric and the golden sets aren't given to the model. The mutation for that item still applies unchanged; the fresh clone at the tag reruns all 448.
- Next: the chapters of Release 3.

## 2026-09-25: chapter 28, the central AI team

- `python/usecases/`: three use cases (one in production, one being built, one proposed), the intake rubric (`rubric.toml`: answers, points, tiers, paths, and the floors an agent's tools set on the answers), the readiness checklist (`readiness.toml`: seven items by tier, the sign-offs each tier needs and who may give them) and the capability library (`library.toml`: ten capabilities, each naming the module that provides it).
- `src/readiness/rules.py`: the rules as pure functions over the record and the evidence. `python -m helpdesk.readiness` (a composition root) gathers the evidence: the policy's verdict on each definition, the last promotion and whether it's current, the catalog's servers, the teams. `check` is the 25th check; `triage FILE` scores one use case; `fingerprint FILE` prints what a sign-off must carry.
- 30 new Python tests (598); 21 new mutations (418), all applied and caught on the working tree before commit.
- Work list: `central-ai-team` done, proved by `tests/test_readiness.py`; `rollout-to-teams` (chapter 29) added.
- Checked with: `node check.mjs` (all 25 checks passed) and `node tools/progress.mjs .`.
- Not run: `--real`, for any command; nothing here calls a model. The customer digest stays "building" because the lab's promotion covers only the triage assistant.
- Then `node tools/mutate.mjs` on the committed tree at `9e4fbb5`: all 418 caught in 19.3 minutes, and the tree unchanged.
- Next: `rollout-to-teams` (chapter 29).

## 2026-09-25: chapter 27, gateways, cost and model routing

- `helpdesk/model/gateway.py`: one front door for every call to a provider. It checks the team's month and its share of the rate limits before each call, routes to the cheapest model on the job's route, moves to another deployment or model when one is down or a model refuses, caches identical requests from one team when the route allows, and records every attempt with the team, the route and the deployment.
- `python -m helpdesk.gateway`: every `--real` call goes through the lab's gateway (`for_agent`); `check` is the 24th check; `demo` runs a made-up organization through it; `report FILE` sums a record by team and route. `agents/policy.toml` has `[teams]`, and the policy's new `team` rule refuses an owner that isn't one.
- `python -m helpdesk.model.cost --cache` and `--keep` price prompt caching and trimming.
- 44 new Python tests (568); 44 new mutations (397) and one updated, all applied and caught on the working tree before commit.
- Work list: `model-gateway` done, proved by `tests/fitness/test_one_door_to_the_provider.py`; `central-ai-team` (chapter 28) added.
- Checked with: `node check.mjs` (all 24 checks passed) and `node tools/progress.mjs .`.
- Not run: `--real`, for any command, so no real call has gone through the gateway. The first paid run of any `--real` command will write `records/gateway.jsonl`; `python -m helpdesk.gateway report ../records/gateway.jsonl` sums it up.
- Then `node tools/mutate.mjs` on the committed tree at `48e1164`: all 397 caught in 18.7 minutes, and the tree unchanged.
- Next: `central-ai-team` (chapter 28).

## 2026-09-25: chapter 26, measuring a harness

- `helpdesk/model/calls.py` and `python -m helpdesk.calls`: a record of every model call, however it ended, with a fingerprint of the system prompt and tools, never the conversation. `python -m helpdesk.gate run --record FILE` writes one.
- `tools/fix-loop.mjs --record FILE`: what each attempt did about a failed check. The loop now stops an attempt that silences a rule (`tools/silenced.mjs`); `tools/stand-in-agent.mjs --silence` shows it.
- `tools/measure.mjs`: rework, reverts, silenced rules, drift fixes and known failures from git history; the fix loop's record, CI runs, pull requests and spend from `records/`; `--save` and `--against` a baseline, with an interval for the change in a rate. `tools/measure-demo.mjs` builds a history to try it on.
- 13 new Python tests (524); 23 new script tests (128); 33 new mutations (353) and two updated, all 35 applied and caught on the working tree before commit.
- Work list: `measure-harness` done, proved by `tools/measure.test.mjs`; `model-gateway` (chapter 27) added.
- Checked with: `node check.mjs` (all 23 checks passed) and `node tools/progress.mjs .`.
- Not run: `--real`, for any command. A record of a real model's calls (its own token counts, refusals and errors) waits for the paid gate run: `python -m helpdesk.gate run --real --max-usd 15 --promote --record ../records/calls.jsonl`. `gh run list` and `gh pr list` against a real repository: the lab has no remote, so the demo writes their shape.
- Then `node tools/mutate.mjs` on the committed tree at `b7d7768`: all 353 caught in 16.8 minutes, and the tree unchanged. After it, the fingerprint moved from the request to the prompt and tools; its mutation and the gate's part label were applied and caught again, and `node check.mjs` passed.
- Next: `model-gateway` (chapter 27).

## 2026-09-25: chapter 23, evaluations as a gate

- `helpdesk/assistant/gating.py` (which differences are regressions and which are noise), `helpdesk/model/budget.py` (the cap) and `helpdesk/gate.py` (`check`, `estimate`, `run`, `run --promote`); `python/evals/gate.json` holds the rules' numbers and `python/evals/promoted.json` the record, promoted on the mock.
- `python -m helpdesk.gate check` is the 23rd check. Every `--real` in `helpdesk.evals`, `helpdesk.judge` and `helpdesk.gate` now needs `--max-usd`, checked before any client is built.
- `.github/workflows/nightly.yml` has a second job, `retirement`, that runs `python -m agent_policy`. Not run: the lab's CI never has.
- 42 new Python tests (511 in all); 30 new mutations (320), each applied and caught before commit.
- Work list: `evals-gate` done, proved by `tests/test_gate.py`; `measure-harness` (chapter 26) added.
- Checked with: `node check.mjs` (all 23 checks passed) and `node tools/progress.mjs .`.
- Not run: `--real`, for any command. Whether a real model passes the gate, and what a real run costs, wait for a paid run: `python -m helpdesk.gate run --real --max-usd 15 --promote`.
- Then `node tools/mutate.mjs` on the committed tree at `eb272e1`: all 320 caught in 16.3 minutes, and the tree unchanged.
- Next: `measure-harness` (chapter 26).

## 2026-09-24: chapter 22, model judges

- `helpdesk/assistant/judging.py`: rubrics, one criterion a call in a fresh conversation, the writer's tool results as the judge's data, verdicts checked against a schema generated from `Verdict` (a malformed one, a refusal or a cut-off answer is an error, never a pass), agreement with a person's labels, the second slot, and the revise loop with a judge. `python -m helpdesk.judge` has `check`, `calibrate`, `compare`, `revise` and `doc`, all on the mock unless `--real`.
- Data: `python/evals/rubrics/reply.json` and `instructions.json`, `python/evals/judged.json` (10 replies, 40 labels by one person), `python/evals/judge-mock.json` (the mock's verdicts, chosen by the lab). Definitions: `python/agents/judge.toml` (the drafter's model) and `judge-second.toml` (another model).
- `python -m helpdesk.judge check` is the 22nd check.
- 49 new Python tests, and the policy command's test now expects four definitions; 26 new mutations, each applied and caught before commit.
- Work list: `model-judge` done, proved by `tests/test_judge.py`; `evals-gate` (chapter 23) added.
- Checked with: `node check.mjs` (all 22 checks passed) and `node tools/progress.mjs .`; then `node tools/mutate.mjs` at `5c6e5e0`, 289 of 289 caught in 14.6 minutes. A fresh clone then showed a stale `.pyc` can outlive a mutation put back within a second; `tools/mutate.mjs` now runs commands with `PYTHONDONTWRITEBYTECODE=1`, with a test and a mutation (290).
- Not run: `--real`, for any command. Which judge agrees with a person more, how often a real drafter and judge settle, and what a real judge says of `AGENTS.md` wait for a paid run; the chapter lists the commands.
- Next: `evals-gate` (chapter 23).

## 2026-09-24: chapter 21, golden sets

- The guardrail tests set `PYTHONIOENCODING` for lint-imports and read its output in that encoding (`67ceb32`); a new test runs them with the variable unset and set to `utf-8`, `cp1252` and `utf-16`. The committed file before the fix gave 12 failed and 12 errors with `utf-8` set.
- `python/evals/tasks.json`: 10 tasks with keys of properties and reference solutions for both tool sets; `python/evals/reasons.json`: 3 rejected drafts. `helpdesk/assistant/grading.py` grades a run against what its own tools returned; `python -m helpdesk.evals` has `check`, `run` (`--vary`, `--suite`, `--set`), `compare` and `team`, all on the mock unless `--real`.
- `python -m helpdesk.evals check` is the 21st check.
- 33 new Python tests (420), 27 new mutations (263), each applied by hand and caught before commit.
- Work list: `golden-set` done, proved by `tests/test_evals.py`.
- Checked with: `node check.mjs` (all 21 checks passed) and `node tools/progress.mjs .` (no problems).
- Not run: `--real`, for any command. Each measurement a real model would make (chapters 11, 14, 19 and 20) waits for a paid run; the chapter lists the commands.
- Then `node tools/mutate.mjs` on the committed tree at `9a1ac04`: all 263 caught in 13.1 minutes, and the tree unchanged.
- Next: `model-judge` (chapter 22).

## 2026-09-24: chapter 20, the agent attack surface

- What a customer writes reaches the assistant as a JSON string, labeled (`helpdesk/services/untrusted.py`); `flag()` marks instruction-shaped text, and proposals filed after reading it carry the flags to `python -m helpdesk.approvals`.
- `python -m helpdesk.injections run` files the red-team tickets in `python/evals/injections.json` and runs the assistant on each as Sam and as Dana, with the mock obeying: nothing changes, flagged or not. `python -m helpdesk.triage --demo injected` runs the first.
- `tests/fitness/test_nothing_sends_outside.py`: nothing the assistant reaches imports a way to another machine.
- `python/requirements-lock.txt` carries every file's sha256; `setup.mjs` installs with `--require-hashes` and builds with `--no-build-isolation` (setuptools 84.0.0 is pinned now). `node tools/lockfiles.mjs` is the 20th check.
- `python/agents/models.toml` and the policy's retirement rules; `python -m agent_policy --today`; the tests fix the day with `AGENT_POLICY_TODAY`. `tests/fitness/test_model_ids_are_pinned.py` found an alias in `helpdesk/model/cost.py`, fixed.
- The MCP catalog pins the digest of the server's tool definitions (`python -m helpdesk.mcp_server --definitions`).
- 37 new Python tests (386 in all), 11 new script tests; 28 new entries in `tools/mutations.mjs` (234 in all), six updated.
- Work list: `injected-text-changes-nothing`, `hash-checked-installs`, `model-retirement` and `mcp-definitions-pinned` added as done, each with its proof.
- Checked with: `node check.mjs` (all 20 checks passed) and `node tools/progress.mjs .` (no problems).
- From 2027-06-24, `python -m agent_policy` fails here by design: claude-opus-5-5 may retire as soon as 2027-09-22. Move the definitions, then update `agents/models.toml` from Anthropic's page.
- Then `node tools/mutate.mjs` on the committed tree at `f6c0c13`: 233 of 234 in 9.7 minutes, and the tree unchanged. The one not counted is no survivor: the control run of chapter 13's Ctrl+C test (`test_the_server_stops_cleanly_when_interrupted`) failed on the unchanged code. Alone it passed 30 runs in a row; with other tests running beside it, it failed once in 8, the server exiting non-zero after Ctrl+Break. The cause isn't found yet; it's a flaky test to fix, recorded here so the next failure isn't a surprise.
- Found verifying from a fresh clone: with one of `anthropic`'s hashes changed, `pip download --require-hashes` took the source archive, whose hash still matched, and built it. `setup.mjs` now adds `--only-binary :all:`, and `node tools/lockfiles.mjs` requires it. Checked with `node check.mjs` (all 20 checks passed) and the same download, now refused.
- The flaky Ctrl+C test, found and fixed: the server printed its first line before uvicorn took the signals, and its handler raised `KeyboardInterrupt`, which Python ignores inside a weakref callback, as during an import, so a stop sent the moment the line appeared was lost now and then. A throwaway script, not kept in the lab, started the server 16 at a time beside 32 busy processes and sent Ctrl+Break the moment it printed, as the test does: 2 of 640 runs never stopped before the fix, 0 of 1,280 after. `Serving` (`helpdesk/mcp_server.py`) prints the line once uvicorn listens, and its handler only sets `should_exit`. A new test and a new mutation (236). Checked with `node check.mjs` (all 20 checks passed).
- Then, from a fresh clone at `56d0822`: `node setup.mjs`, `node check.mjs` (all 20 checks passed) and `node tools/mutate.mjs`: all 236 caught in 11.7 minutes, and the tree unchanged.
- Found, not fixed: with `PYTHONIOENCODING=utf-8` set, as some shells set it, the 12 tests in `tests/guardrails/test_layers_contract.py` fail, because they read lint-imports' output in the locale's encoding (`text=True`) while it writes UTF-8. Unset, they pass. Give the subprocess its encoding explicitly.
- Next: `golden-set`, the first item still to do.

## 2026-09-24: chapter 19, permissions and human approval

- `draft_reply` and `close_ticket` (`helpdesk/assistant/proposing.py`) check what the person may change and file a proposal; `python -m helpdesk.approvals` is where a person approves or rejects it (`helpdesk/services/decisions.py`, which only that command may import). Approving re-checks everything and commits the decision, the change and its record together; a rejection's reason shows on the ticket for the assistant; closing needs a lead; every step is in `approval_log`.
- `python -m helpdesk.triage --demo propose|redraft --db FILE` runs the scripted flow.
- The agent policy requires `[approval]` for every tool in `[writes]`, at least the policy's level.
- `.claude/settings.json`: deny rules for force pushes and a PreToolUse guard for destructive shell commands (`tools/hooks/destructive-guard.mjs`): ask where a prompt can be shown, deny where it can't, deny on failure.
- 30 new Python tests (349 in all), 6 new script tests; 36 new entries in `tools/mutations.mjs` (206 in all).
- Work list: `draft-reply` and `approval-before-sending` marked done; `writers-declare-approval` and `destructive-command-guard` added as done; each with its proof.
- Checked with: `node check.mjs` (all 19 checks passed) and `node tools/progress.mjs .` (no problems).
- Then `node tools/mutate.mjs` on the committed tree at `e12933f`: all 206 caught in 8.8 minutes, and the tree unchanged.
- Next: `golden-set`, the first item still to do.

## 2026-09-24: chapter 14, multi-agent patterns

- `python -m helpdesk.patterns batch`: an orchestrator (`agents/orchestrator.toml`, tools `find_tickets` and a new `delegate_customer`) hands each customer's open and pending tickets to a worker with its own context and only `get_ticket` and `search_kb` (`helpdesk/assistant/team.py`). Each worker's drafts are citation-checked against its own transcript, and the orchestrator gets a short report. After the run, the code counts every customer in the batch as drafted, failed or never delegated, whatever the orchestrator's summary says; `--fail ben` cuts one worker off to show it.
- `python -m helpdesk.patterns revise`: a draft goes back with the citation check's findings until it passes, comes back unchanged, or reaches 3 rounds (`helpdesk/assistant/revise.py`). `run_agent` takes a `history` so a round continues the conversation.
- `python -m helpdesk.patterns compare`: the same batch of 8 tickets by one agent all at once, one agent a ticket at a time, and the team, in characters sent and estimated tokens.
- `passages_given` moved from `triage.py` to `helpdesk/assistant/tools.py`, so the triage assistant and the workers use the same one. `delegate_customer` joined the policy's tools and the tool-definition fitness test.
- 28 new Python tests (319 in all); 15 new entries in `tools/mutations.mjs` (170 in all).
- Work list: `multi-agent-patterns` added as done, with its proof.
- Checked with: `node check.mjs` (all 19 checks passed) and `node tools/progress.mjs .` (no problems).
- Follow-up: `node tools/mutate.mjs` on the committed tree at `dc45cfb` caught 169 of 170 in 9.7 minutes; the other was stale, because the policy's tool list it changes had gained `delegate_customer`. Fixed, and a new test in `tools/mutate.test.mjs` fails `node check.mjs` when any entry's text isn't in its file exactly once (it failed on this entry before the fix). Checked with `node --test tools/mutate.test.mjs` (6 passed) and the entry run alone (caught).
- Then `node tools/mutate.mjs` on the committed tree at `6deb3b5`: all 170 caught in 9.2 minutes, and the tree unchanged.
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 13, governing MCP servers

- `python -m helpdesk.mcp_server --http` serves the MCP server over Streamable HTTP as an OAuth resource server: tokens from the lab's test issuer, checked for type, signature, issuer, expiry and audience (`mcp_governance/tokens.py`); a scope for each operation, 403 `insufficient_scope` without it; the person from the token; the `Authorization` header removed before the MCP server sees the request; an audit record for every request (`mcp_governance/resource_server.py`, `audit.py`).
- `python -m mcp_governance` checks the catalog of approved servers (`python/catalog/servers.toml`) against its rules, the 19th check; the HTTP server refuses to start if it differs from its entry. `allowlist` and `audit` are its other commands.
- `python -m helpdesk.mcp_client --url` speaks HTTP with a token from the lab's issuer (`--as`, `--scope`, `--audience`).
- 64 new Python tests (290 in all); 22 new entries in `tools/mutations.mjs` (154 in all).
- Work list: `mcp-governance` added as done, with its proof.
- Checked with: `node check.mjs` (all 19 checks passed), `node tools/mutate.mjs` (all 154 caught in 7.8 minutes, on the committed tree at `f9104e1`, which it left unchanged) and `node tools/progress.mjs .` (no problems).
- Follow-up: Ctrl+C (Ctrl+Break on Windows) now stops the HTTP server with exit code 0 and `helpdesk MCP server: stopped.`, where Ctrl+Break had ended it with exit code 3; a new test and a new mutation (291 tests, 155 mutations). Checked with `node check.mjs` (all 19 checks passed) and `node tools/mutate.mjs` (all 155 caught in 7.8 minutes, on the committed tree at `53bd95c`, which it left unchanged).
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 12, an MCP server

- `python -m helpdesk.mcp_server` offers the triage assistant's three tools, the help articles and each ticket as resources, and a `draft_reply` prompt over stdio, through the official MCP Python SDK (`mcp` 2.2.0, pinned with the 14 packages it brings). It acts for `HELPDESK_STAFF` and refuses to start without a known person; every tool, resource and prompt applies `helpdesk/services/access.py` for that person.
- `python -m helpdesk.mcp_client` plays the host: starts the server, sets its environment, and speaks JSON-RPC a line at a time (`--wire` shows it, `--legacy` uses the 2025-11-25 handshake).
- A fifth import contract keeps the SDK in `helpdesk.mcp_server`.
- 21 new Python tests (226 in all); 11 new entries in `tools/mutations.mjs` (132 in all).
- Work list: `mcp-server` marked done, with its proof.
- Checked with: `node check.mjs` (all 18 checks passed), `node tools/mutate.mjs` (all 132 caught in 6.2 minutes, in the working copy at `6524d60`) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

## 2026-09-23: chapter 11, designing tools for agents

- The triage assistant acts for one member of staff (`--as`, default sam), and its tools show only what that person may see: `helpdesk/services/access.py` holds the rule, and every tool applies it to every ticket it reads, lists or counts. A hidden ticket and a missing one get the same message. The sample data grew to 12 tickets, 5 customers, 3 staff and 4 replies, so the rule and the pages have something to act on.
- Tools: `get_ticket` now returns the ticket in context (names, replies, the customer's other tickets); new `find_tickets` lists in handling order, five to a page; `search_kb` unchanged. Every schema is strict and closed to extra arguments, and the toolbox checks the whole schema before a tool runs, reporting every problem at once. Unexpected exceptions come back as results that say not to retry, and results over 6,000 characters are cut with a note. The Anthropic adapter sends `strict: true` and leaves out the keywords strict mode refuses.
- `python -m helpdesk.tools` (`list`, `schema`, `call`, `compare`) is a new composition root; `compare` measures two tasks against a narrow set with one tool per table (`helpdesk/assistant/narrow.py`).
- 42 new Python tests (205 in all); 28 new entries in `tools/mutations.mjs` (121 in all), and one existing entry updated for the policy's new tool list.
- Work list: `tools-act-for-a-person` added as done, with its proof. The description of `triage-tools-read-only` said "exactly two tools"; it was reworded to what the item guards, read-only, because the count changed and the property didn't.
- Checked with: `node check.mjs` (all 18 checks passed), `node tools/mutate.mjs` (all 121 caught in 5.5 minutes, in the working copy at `f5c7df2`) and `node tools/progress.mjs .` (no problems).
- Next: `draft-reply`, still the first item to do.

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
