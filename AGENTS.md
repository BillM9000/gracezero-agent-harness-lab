# AGENTS.md

Instructions for any coding agent, and any person, working in this repository. `CLAUDE.md` points here, so every tool reads the same rules.

## What this is

The companion lab for a book on AI platform engineering: a small helpdesk service in Python, a TypeScript client, a deterministic mock model, and the guardrails the book teaches, each one running in CI.

## Layout

| Path | What it is |
|---|---|
| `python/src/helpdesk/api/` | HTTP routes (FastAPI). Calls services only. |
| `python/src/helpdesk/services/` | Business rules. Calls the data layer. |
| `python/src/helpdesk/data/` | SQL and the SQLite connection. |
| `python/src/helpdesk/model/` | The model interface, a deterministic mock, stop-reason handling (`stops.py`) and cost arithmetic (`cost.py`). Imports nothing else from the helpdesk. |
| `python/src/toymodel/` | Chapter 2's toy tokenizer and next-word model. Teaching code, not part of the helpdesk. |
| `python/src/helpdesk/main.py` | Composition root: the only module that wires the layers together. |
| `python/tests/` | Tests. `tests/guardrails/` proves each guardrail catches what it claims to. |
| `ts/` | TypeScript client and command-line tool for the API. |
| `postings/` | The coded job-postings sample from chapter 1, the script that counts it, and a template for coding your own. |
| `.github/workflows/ci.yml` | CI: runs every check below. |

## Commands

Python, from `python/` (use `.venv/Scripts/` on Windows, `.venv/bin/` elsewhere):

- Set up: `python -m venv .venv`, then `pip install -r requirements-lock.txt` and `pip install -e . --no-deps`
- Test: `pytest`
- Lint: `ruff check .` and `ruff format --check .`
- Guardrails: `lint-imports`
- Run: `uvicorn --factory helpdesk.main:create_default_app` (`HELPDESK_DB` sets the database file)
- Chapter 2 demos: `python -m toymodel tokens "reset my password"`, `python -m toymodel next "reset emails can take up to"`, `python -m helpdesk.model.cost`

TypeScript, from `ts/`:

- Set up: `npm ci`
- Type-check: `npm run typecheck`
- Test: `npm test`
- Try the CLI: `npm run cli -- tickets open` (`--url` or `HELPDESK_URL` sets the server)

Job postings, from the repository root:

- Count the sample: `node postings/tally.mjs postings/sample-2026-09-22.json`
- Test: `node --test postings/tally.test.mjs`
- `postings/sample-2026-09-22.json` is a dated record. Never edit its codes; code a new sample in a new file instead.

## Rules

1. Layers run api, then services, then data. Routes never import `helpdesk.data`: move the query into a service and call that. `lint-imports` enforces this, and its failure message says how to fix it.
2. `helpdesk.model` imports nothing from the helpdesk. Pass it what it needs as arguments.
3. Only `helpdesk/main.py` wires the layers together.
4. Tests use the mock model and never call a real model or the network.
5. Code that wants a model's text calls `helpdesk.model.stops.final_text`, never `response.text` directly, so a refusal or a cut-off answer can't pass as a finished one.
6. Warnings fail the Python test run. Fix the cause instead of silencing it; the one exception, raised inside Starlette, is listed in `pyproject.toml`.
7. A change is done when every command above passes. Record it in `CHANGELOG.md` in the same commit.
8. No secrets in the repository.
