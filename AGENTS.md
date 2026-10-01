# AGENTS.md

For any coding agent or person working here. `CLAUDE.md` imports this file, so every tool reads the same rules.

## What this is

The companion lab for a book on AI platform engineering: a Python helpdesk, a TypeScript client, a mock model, and the book's guardrails, each run in CI.

## Layout

| Path | What it is |
|---|---|
| `python/src/helpdesk/api/` | HTTP routes (FastAPI) and the request and response models. |
| `python/src/helpdesk/services/` | Business rules: who may see and change what (`access.py`), retrieval and citations, the approval queue, customers' text as data. |
| `python/src/helpdesk/data/` | SQL and the SQLite connection. |
| `python/src/helpdesk/assistant/` | The triage assistant: its loop (`agent.py`), tools (`tools.py`; `proposing.py` for those that only file a proposal), patterns and judges. A tool acts for the person it was built for, never one in its arguments. |
| `python/src/helpdesk/model/` | The model interface, a mock, the provider clients (Anthropic's, OpenAI's), stop reasons (`stops.py`), costs (`cost.py`) and the gateway (`gateway.py`, chapter 27). Imports nothing else from the helpdesk. |
| `python/src/toymodel/` | Chapter 2's toy tokenizer and next-word model. |
| `python/src/helpdesk_lint/` | The lab's own lint rule (chapter 17), run by `python -m helpdesk_lint`. |
| `python/agents/` | Agent definitions, the platform's policy for them and the models' retirement dates (`models.toml`), checked by `python/src/agent_policy/` (chapters 18, 20). |
| `python/catalog/` | Approved MCP servers and their rules' data, checked by `python/src/mcp_governance/`, with the HTTP server's token checks and audit log. |
| The modules directly in `python/src/helpdesk/` | Composition roots: the web service (`main.py`) and the commands below. |
| `python/tests/` | Tests. `tests/guardrails/` proves each guardrail catches what it claims to; `tests/fitness/` checks properties of the code as a whole (chapter 15). |
| `contracts/openapi.json` | The API contract, generated from the Python models by `python -m helpdesk.contract`. |
| `ts/` | TypeScript client and command-line tool for the API. `src/api-types.ts` is generated from the contract. Import rules: `eslint.config.js` and `.dependency-cruiser.cjs`. |
| `boundaries/` | The helpdesk's layer rule in Go, Java and .NET (chapter 16). Only CI runs them. |
| `postings/` | Chapter 1's job-postings sample, tally script and template. |
| `tools/` | Scripts the chapters build; each that checks something has a test beside it. See Scripts below. |
| `setup.mjs`, `check.mjs` | Set up everything, and run every check. |
| `progress/` | The work list (`features.json`) and the session log (`log.md`). See Starting a session below. |
| `.github/workflows/` | CI: `ci.yml` (every check), `docs.yml` (Markdown-only changes), `nightly.yml` (`node tools/mutate.mjs`, chapter 24; retirement dates, 23). |
| `.claude/settings.json` | Claude Code's settings: deny rules, a guard before shell commands and a Stop hook, both in `tools/hooks/` (chapters 19 and 25). |

## Starting a session

1. Get your bearings: `git log --oneline -10`, and `node tools/progress.mjs` for what's done, what's next and what the last session left.
2. Run `node setup.mjs` and `node check.mjs`, so you know everything passes first.
3. Work on one item from `progress/features.json`. Mark it done only when a test proves it, and name that test as its proof.
4. Before you stop, add a dated entry at the top of `progress/log.md`: what changed, how you checked it, and what comes next.

## Commands

Everything, from the repository root:

- Set up: `node setup.mjs` (`python/.venv`, the pinned packages, `npm ci`)
- Check: `node check.mjs` (all <!-- claim: checks -->24 checks; CI runs the same command). Model retirement dates are checked as of the latest `read` in `python/agents/models.toml`; `AGENT_POLICY_TODAY=YYYY-MM-DD` sets another.
- Check quickly: `node check.mjs --fast` (no test suites; the full run counts)
- After changing a pin: `node tools/lockfiles.mjs hashes`, `node setup.mjs`, then `node tools/install-paths.mjs`.
- After changing a request or response model: `node tools/regenerate.mjs`, then fix what `node check.mjs` reports.

Python, from `python/` (use `.venv/Scripts/` on Windows, `.venv/bin/` elsewhere):

- Test: `pytest`
- Lint: `ruff check .` and `ruff format --check .`
- Guardrails: `lint-imports`, and `python -m helpdesk_lint` for the lab's own rule
- Policies: `python -m agent_policy` for agents, as of today (`--today`: another day), `python -m mcp_governance` for MCP servers (also `allowlist`, `audit`); `tests/policy_fixtures/` and `tests/catalog_fixtures/` show what each rule accepts and refuses
- Run: `uvicorn --factory helpdesk.main:create_default_app`
- The triage assistant: `python -m helpdesk.triage` (the mock, scripted); `--real "..."` calls Anthropic's API
- Red team: `python -m helpdesk.injections run`, and `flag "text"`
- Golden sets, judges and the gate: `python -m helpdesk.evals`, `helpdesk.judge` and `helpdesk.gate`, each with `check`; `--help` lists the rest (`--real` is billed and needs `--max-usd`); `python -m helpdesk.calls FILE` sums up `gate run --record FILE`
- The gateway: `python -m helpdesk.gateway check`, `demo` and `report FILE`; real calls are recorded in `records/gateway.jsonl`
- Knowledge base: `python -m helpdesk.kb eval` checks retrieval; also `query`, `cite`, `chunks`, `size`
- Tools: `python -m helpdesk.tools list`, `schema`, `call` and `compare`
- Patterns: `python -m helpdesk.patterns revise`, `batch` and `compare`
- Approvals: `python -m helpdesk.approvals list --as sam`; also `show`, `approve`, `reject`, `log`
- MCP: `python -m helpdesk.mcp_client --as sam tools` (also `call`, `read`, `prompt`); `python -m helpdesk.mcp_server --http`

TypeScript, from `ts/`:

- Type-check: `npm run typecheck`
- Import rules: `npm run lint` (ESLint, with the lab's own rule in `scripts/eslint-rules/`) and `npm run deps` (dependency-cruiser)
- Test: `npm test`
- Try the CLI: `npm run cli -- tickets open`

Scripts, from the repository root. Each has a test file beside it: run `node --test` on that file.

- `node postings/tally.mjs postings/sample-2026-09-22.json` counts chapter 1's sample, a dated record: never edit its codes.
- `node tools/install-paths.mjs` checks setup's Windows path limit against the installed packages (chapter 5).
- `node tools/lockfiles.mjs` checks every pin has its hashes and what's installed matches the locks (chapter 20).
- `node tools/instruction-files.mjs <path>` reports what each instruction file loads, and when (chapter 6).
- `node tools/doc-claims.mjs [path]` checks the paths and marked numbers in these documents (chapter 8).
- `node tools/progress.mjs [path]` shows the work list and the last log entry, and fails if a done item's test doesn't exist (chapter 10).
- `node tools/mutate.mjs` breaks each guard in `tools/mutations.mjs` in turn and requires a test to catch it (`--list` lists them; `--only PREFIX` runs a group); when you add a guard, add its entry (chapter 24).
- `node tools/fix-loop.mjs --agent "<command>"` gives failing checks to an agent command, with limits (chapter 25).
- For readers, each described in its header and the README: `tools/harness-inventory.mjs`, `tools/rework.mjs`, `tools/measure.mjs`.

## Rules

1. Layers run api and assistant (siblings that never import each other), then services, then data. Neither routes nor the assistant import `helpdesk.data`: move the query into a service and call that. `lint-imports` enforces this. In `ts/`, the CLI uses the client and the client uses the types; only `src/cli.ts` uses Node's built-in modules, and only `src/types.ts` imports `src/api-types.ts`. `npm run lint` and `npm run deps` enforce this.
2. `helpdesk.model` imports nothing from the helpdesk, and nothing else imports a provider's SDK: pass code that needs a model a `ModelClient`. A real one comes only from `helpdesk.gateway.for_agent`.
3. Only the composition roots (see Layout) wire the layers together.
4. Tests use the mock model and never reach another machine; a server a test starts listens on 127.0.0.1.
5. Code that wants a model's text calls `helpdesk.model.stops.final_text`, never `response.text` directly, so a refusal or a cut-off answer can't pass as a finished one. `python -m helpdesk_lint` enforces this; a line with a real reason to read the text says so in a `# HDK101: <why>` comment.
6. Warnings fail the Python test run: fix the cause (one exception, in `pyproject.toml`).
7. A change is done when `node check.mjs` passes. Record it in `CHANGELOG.md` in the same commit.
8. No secrets in the repository.
9. Keep this file a map, under 200 lines and about 4,000 estimated tokens (`node check.mjs` measures). Put detail where the tasks that need it meet it (an error message, a test).
10. Never edit a generated file by hand. `contracts/openapi.json` and `ts/src/api-types.ts` come from the code: change their source and regenerate them. `node check.mjs` fails if either is out of date.
11. A number in these documents that a script can count is marked `<!-- claim: NAME -->`, and `node check.mjs` checks it; a new kind of number needs a counter in `tools/doc-claims.mjs`. A claim about behavior, such as "read-only," needs a test instead.
12. When a check fails, fix what it reports. Never weaken, skip or delete a check, test or rule to get a pass; if a check is wrong, stop and say why.
