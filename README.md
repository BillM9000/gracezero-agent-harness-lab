# agent-harness-lab

The companion lab for a plain-English book on AI platform engineering by Bill McCoy, in progress. Each guardrail the book teaches is built here, with a test that proves it catches what it claims to.

## What is here so far

- **A small helpdesk service** in Python (FastAPI on SQLite): tickets, replies and a knowledge base, with invented sample data. It is split into three layers (routes, services, data), wired together in one place.
- **A TypeScript client and command-line tool** for the helpdesk API.
- **A deterministic mock model**, so everything runs offline and costs nothing, and **a client for Anthropic's API** for when you want a real model.
- **A triage assistant**: the smallest working agent, a model in a loop with two read-only tools and a turn limit. `python -m helpdesk.triage` runs it against the mock.
- **The first guardrail**: <!-- claim: import-contracts -->3 import rules that keep the layers apart, each with a failure message that says how to fix the violation, and tests that plant each violation in a copy of the code to prove the rule catches it.
- **The job-postings sample from chapter 1**: <!-- claim: postings -->45 coded United States postings, the script that counts them, and a template for coding your own.
- **A harness inventory** (`node tools/harness-inventory.mjs <path>`): lists the evidence any repository's files give for each of the eight parts of a harness from chapter 4.
- **One command to set up and one to check** (chapter 5): `node setup.mjs` and `node check.mjs`, the same two commands CI runs.
- **An API contract generated from the code** (chapter 7): `contracts/openapi.json` comes from the Python models, the TypeScript client's types come from the contract, and `node check.mjs` fails if either falls behind.
- **A work list and a session log** (chapter 10): `progress/features.json` says what's done and what's next, each done item naming the test that proves it, and `progress/log.md` records what each session did and how it checked it. `node tools/progress.mjs` shows both.
- **A check on what the documentation claims** (chapter 8): `node tools/doc-claims.mjs` fails when a path this README or `AGENTS.md` names is gone, or when a number marked in them no longer matches the repository.
- **An instruction-file check** (chapter 6): `node tools/instruction-files.mjs <path>` reports what each instruction file puts in front of an agent at the start of a session, counting the files it imports, and flags a file over budget, an import that doesn't load, and a `CLAUDE.md` that hides an `AGENTS.md`.
- **Chapter 2's toys and tools**: a toy tokenizer and next-word model that show why token counts and answers vary, a cost calculator for conversations that resend their history, and a check that refuses to treat a refused or cut-off answer as finished.

Coming chapter by chapter: tools that change things, behind human approval; hooks; an MCP server; evaluations; and the same boundary rule in Go, Java and .NET.

## Quick start

You need Python and Node. The lab is tested with Python 3.14 and Node 24. The Python package declares 3.12 as its minimum, which hasn't been tested.

On Windows, clone into a short folder such as `C:\src`. One of the Python packages installs files with very long names, and Windows limits a whole path to 260 characters unless long paths are enabled. The setup script checks the length before it installs anything, and says what to do if your folder's path is too long.

From the repository's root folder:

```bash
node setup.mjs
node check.mjs
```

`setup.mjs` creates `python/.venv`, installs the pinned Python packages and the TypeScript packages. `check.mjs` runs every check and prints one line each; CI runs the same two commands. Run `node setup.mjs` again after pulling a new chapter, in case the pinned packages changed.

Each chapter's state of the repository has a tag: `git checkout ch03` shows the lab as chapter 3 left it.

`AGENTS.md` has every individual command and the rules for changing the code.

## License

MIT. See `LICENSE`.
