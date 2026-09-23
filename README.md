# agent-harness-lab

The companion lab for a plain-English book on AI platform engineering by Bill McCoy, in progress. Each guardrail the book teaches is built here, with a test that proves it catches what it claims to.

## What is here so far

- **A small helpdesk service** in Python (FastAPI on SQLite): tickets, replies and a knowledge base, with invented sample data. It is split into three layers (routes, services, data), wired together in one place.
- **A TypeScript client and command-line tool** for the helpdesk API.
- **A deterministic mock model**, so everything runs offline and costs nothing. A real model arrives with the chapter that builds the first agent.
- **The first guardrail**: import rules that keep the layers apart, each with a failure message that says how to fix the violation, and tests that plant each violation in a copy of the code to prove the rule catches it.
- **The job-postings sample from chapter 1**: 33 coded United States postings, the script that counts them, and a template for coding your own.
- **Chapter 2's toys and tools**: a toy tokenizer and next-word model that show why token counts and answers vary, a cost calculator for conversations that resend their history, and a check that refuses to treat a refused or cut-off answer as finished.

Coming chapter by chapter: the triage assistant, hooks, an MCP server, evaluations, and the same boundary rule in Go, Java and .NET.

## Quick start

Tested with Python 3.14 and Node 24.

```bash
cd python
python -m venv .venv
.venv/bin/pip install -r requirements-lock.txt   # on Windows: .venv\Scripts\pip
.venv/bin/pip install -e . --no-deps
.venv/bin/pytest
.venv/bin/lint-imports
.venv/bin/uvicorn --factory helpdesk.main:create_default_app
```

In a second terminal:

```bash
cd ts
npm ci
npm test
npm run cli -- tickets open
```

`AGENTS.md` has the full list of commands and the rules for changing the code.

## License

MIT. See `LICENSE`.
