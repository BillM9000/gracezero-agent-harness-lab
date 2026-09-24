# AGENTS.md

Instructions for any coding agent or person working here. `CLAUDE.md` imports this file, so every tool reads the same rules.

## What this is

The companion lab for a book on AI platform engineering: a Python helpdesk, a TypeScript client, a mock model, and the book's guardrails, each run in CI.

## Layout

| Path | What it is |
|---|---|
| `python/src/helpdesk/api/` | HTTP routes (FastAPI) and the request and response models, the one place the API's shapes are written. Calls services only. |
| `python/src/helpdesk/services/` | Business rules, including what each member of staff may see (`access.py`, chapter 11), and retrieval and citation checks (chapter 9). Calls the data layer. |
| `python/src/helpdesk/data/` | SQL and the SQLite connection. |
| `python/src/helpdesk/assistant/` | The triage assistant: an agent loop (`agent.py`), its tools (`tools.py`), and a narrow set kept only to compare against (`narrow.py`). A tool acts for the person it was built for, never one named in its arguments. Calls services, never the data layer. |
| `python/src/helpdesk/model/` | The model interface, a deterministic mock, the Anthropic client (`anthropic_client.py`), stop-reason handling (`stops.py`) and cost arithmetic (`cost.py`). Imports nothing else from the helpdesk. |
| `python/src/toymodel/` | Chapter 2's toy tokenizer and next-word model. |
| `python/src/helpdesk_lint/` | The lab's own lint rule (chapter 17), run by `python -m helpdesk_lint`. |
| `python/agents/` | Agent definitions (`triage.toml`) and the platform's policy for them (`policy.toml`), checked by `python/src/agent_policy/` (chapter 18). |
| `python/src/helpdesk/main.py`, `triage.py`, `kb.py`, `tools.py`, `mcp_server.py` | Composition roots: the web service, the triage assistant, the knowledge base's and tools' command lines, and the MCP server (chapter 12). |
| `python/tests/` | Tests. `tests/guardrails/` proves each guardrail catches what it claims to; `tests/fitness/` checks properties of the code as a whole (chapter 15). |
| `contracts/openapi.json` | The API contract, generated from the Python models by `python -m helpdesk.contract`. |
| `ts/` | TypeScript client and command-line tool for the API. `src/api-types.ts` is generated from the contract. Import rules: `eslint.config.js` and `.dependency-cruiser.cjs`. |
| `boundaries/` | The helpdesk's layer rule in Go, Java and .NET (chapter 16). Only CI runs them. |
| `postings/` | The coded job-postings sample from chapter 1, the script that counts it, and a template for coding your own. |
| `tools/` | Scripts the chapters build; each one that checks something has a test beside it. See Scripts below. |
| `setup.mjs`, `check.mjs` | Set up everything, and run every check. |
| `progress/` | The work list (`features.json`) and the session log (`log.md`). See Starting a session below. |
| `.github/workflows/` | CI: `ci.yml` runs setup and every check, `docs.yml` checks Markdown-only changes, `nightly.yml` runs `node tools/mutate.mjs` (chapter 24). |
| `.claude/settings.json` | Claude Code's hooks: when the agent stops, `tools/hooks/stop-check.mjs` runs `node check.mjs --fast` and sends any failure back (chapter 25). |

## Starting a session

1. Get your bearings: `git log --oneline -10` for what changed lately, and `node tools/progress.mjs` for what's done, what's next and what the last session left.
2. Run `node setup.mjs` and `node check.mjs`, so you know everything passes before you change anything.
3. Work on one item from `progress/features.json`. Mark it done only when a test proves it, and name that test as its proof.
4. Before you stop, add a dated entry at the top of `progress/log.md`: what changed, how you checked it, and what comes next.

## Commands

Everything, from the repository root:

- Set up: `node setup.mjs` (creates `python/.venv`, installs the pinned packages, runs `npm ci`)
- Check: `node check.mjs` (all <!-- claim: checks -->18 checks; CI runs the same command)
- Check quickly: `node check.mjs --fast` skips the three test suites, for after each edit; the full run is what counts
- After changing `python/requirements-lock.txt`: run `node setup.mjs`, then `node tools/install-paths.mjs`; if it fails, its message says what to change.
- After changing a request or response model: `node tools/regenerate.mjs` (the API contract, then the TypeScript types), then `node check.mjs`, and fix what the type-check reports.

Python, from `python/` (use `.venv/Scripts/` on Windows, `.venv/bin/` elsewhere):

- Test: `pytest`
- Lint: `ruff check .` and `ruff format --check .`
- Guardrails: `lint-imports`, and `python -m helpdesk_lint` for the lab's own rule
- Agent definitions: `python -m agent_policy` checks `agents/*.toml` against `agents/policy.toml`; `tests/policy_fixtures/` shows what each rule accepts and refuses
- Run: `uvicorn --factory helpdesk.main:create_default_app` (`HELPDESK_DB` sets the database file)
- Chapter 2 demos: `python -m toymodel tokens|next <text>`, `python -m helpdesk.model.cost`
- The triage assistant: `python -m helpdesk.triage` (the mock, scripted); `--real "..."` calls Anthropic's API, with a credential such as `ANTHROPIC_API_KEY`
- Knowledge base: `python -m helpdesk.kb eval` checks retrieval against `python/evals/kb_questions.json`; also `query`, `cite`, `chunks`, `size`
- Tools: `python -m helpdesk.tools list`, `schema`, `call` (one call, `--as` a member of staff) and `compare`
- MCP: `python -m helpdesk.mcp_client --as sam tools` starts the server for Sam and asks it; also `call`, `read`, `prompt`, `--wire`

TypeScript, from `ts/`:

- Set up: `npm ci`
- Type-check: `npm run typecheck`
- Import rules: `npm run lint` (ESLint, one file at a time, with the lab's own rule in `scripts/eslint-rules/`) and `npm run deps` (dependency-cruiser, between files)
- Test: `npm test`
- Try the CLI: `npm run cli -- tickets open` (`--url` or `HELPDESK_URL` sets the server)

Scripts, from the repository root. Each has a test file beside it: run `node --test` on that file.

- `node postings/tally.mjs postings/sample-2026-09-22.json` counts chapter 1's postings sample. The sample is a dated record: never edit its codes; code a new sample in a new file instead.
- `node tools/harness-inventory.mjs <path>` lists the evidence a repository's files give for each part of a harness (chapter 4).
- `node tools/install-paths.mjs` checks setup's Windows path limit against the installed packages (chapter 5).
- `node tools/instruction-files.mjs <path>` reports what each instruction file loads, and when (chapter 6).
- `node tools/doc-claims.mjs [path]` checks the paths and marked numbers in these documents (chapter 8).
- `node tools/progress.mjs [path]` shows the work list and the last log entry, and fails if a done item's test doesn't exist (chapter 10).
- `node tools/mutate.mjs` breaks each guard in `tools/mutations.mjs` in turn and requires a test to catch it; when you add a guard, add its entry (chapter 24).
- `node tools/fix-loop.mjs --agent "<command>"` gives failing checks to an agent command, at most three times, and stops if nothing changes or the checks do; `node tools/stand-in-agent.mjs` stands in for an agent (chapter 25).
- `node tools/rework.mjs [path]` shows where fixes landed on recent agent work, from git history alone; `node tools/rework-demo.mjs <folder>` builds a history to try it on (chapter 31).

## Rules

1. Layers run api and assistant (siblings that never import each other), then services, then data. Neither routes nor the assistant import `helpdesk.data`: move the query into a service and call that. `lint-imports` enforces this, and its failure message says how to fix it. In `ts/`, the CLI uses the client and the client uses the types; only `src/cli.ts` uses Node's built-in modules, and only `src/types.ts` imports `src/api-types.ts`. `npm run lint` and `npm run deps` enforce this.
2. `helpdesk.model` imports nothing from the helpdesk, and nothing else imports the `anthropic` SDK. Pass the model what it needs as arguments, and pass code that needs a model a `ModelClient`.
3. Only the composition roots (see Layout) wire the layers together.
4. Tests use the mock model and never call a real model or the network.
5. Code that wants a model's text calls `helpdesk.model.stops.final_text`, never `response.text` directly, so a refusal or a cut-off answer can't pass as a finished one. `python -m helpdesk_lint` enforces this; a line with a real reason to read the text says so in a `# HDK101: <why>` comment.
6. Warnings fail the Python test run. Fix the cause instead of silencing it; the one exception, raised inside Starlette, is listed in `pyproject.toml`.
7. A change is done when `node check.mjs` passes. Record it in `CHANGELOG.md` in the same commit.
8. No secrets in the repository.
9. Keep this file a map: under 200 lines and about 4,000 estimated tokens, which `node check.mjs` measures. Put detail that only some tasks need where those tasks meet it, such as an error message or a test, and name any other file with a reason to read it.
10. Never edit a generated file by hand. `contracts/openapi.json` and `ts/src/api-types.ts` come from the code: change their source and regenerate them. `node check.mjs` fails if either is out of date.
11. A number in these documents that a script can count is marked `<!-- claim: NAME -->`, and `node check.mjs` checks it; a new kind of number needs a counter in `tools/doc-claims.mjs`. A claim about behavior, such as "read-only," needs a test instead, like the one in `python/tests/test_triage_tools.py`.
12. When a check fails, fix what it reports. Never weaken, skip or delete a check, test or rule to get a pass; if a check is wrong, stop and say why.
