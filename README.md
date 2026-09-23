# agent-harness-lab

The companion lab for a plain-English book on AI platform engineering by Bill McCoy, in progress. Each guardrail the book teaches is built here, with a test that proves it catches what it claims to.

## What is here so far

- **A small helpdesk service** in Python (FastAPI on SQLite): tickets, replies and a knowledge base, with invented sample data. It is split into three layers (routes, services, data), wired together in one place.
- **A TypeScript client and command-line tool** for the helpdesk API.
- **A deterministic mock model**, so everything runs offline and costs nothing, and **a client for Anthropic's API** for when you want a real model.
- **A triage assistant**: the smallest working agent, a model in a loop with two read-only tools and a turn limit. `python -m helpdesk.triage` runs it against the mock.
- **The first guardrail**: <!-- claim: import-contracts -->4 import rules that keep the layers apart and keep the model vendor's SDK inside one package, each with a failure message that says how to fix the violation, and tests that plant each violation in a copy of the code to prove the rule catches it.
- **Import rules for the TypeScript package too** (chapter 16): ESLint for the rule that fits one file at a time, and dependency-cruiser for the rules between files, with tests that plant each violation and check that every file was read. The same layer rule in Go, Java and .NET is in `boundaries/`, run only by CI.
- **Checks in tiers** (chapter 24): `node check.mjs --fast` runs everything but the test suites in seconds; CI runs the full set on every change to code, only the document checks on a change to Markdown alone, and every night `node tools/mutate.mjs` breaks each guard listed in `tools/mutations.mjs` and requires a test to catch it.
- **Failures sent back to the agent** (chapter 25): when a coding agent says it's done, a Claude Code hook (`.claude/settings.json`) runs the fast checks and sends any failure back with how to rerun them and what doesn't count as a fix, at most three rounds in a row. For pipelines, `node tools/fix-loop.mjs` hands failing checks to any agent command, with a cap on attempts, and stops early when an attempt changes nothing, commits, or changes the checks themselves: every check's code and data, listed for each check in `tools/protected.mjs` (a test fails when a check has no entry), and a tool's configuration file in any folder.
- **Agent definitions checked against a policy** (chapter 18): the triage assistant is defined in `python/agents/triage.toml`, and `python -m agent_policy` checks it against the platform's rules in `python/agents/policy.toml` (approved models, a cost cap per call, a turn limit, known tools) before it may run. A corpus of small definitions in `python/tests/policy_fixtures/` says what each rule accepts and refuses.
- **The lab's own lint rules** (chapter 17): `python -m helpdesk_lint` makes code read a model's text through `final_text`, and every exception must say why; a custom ESLint rule sends the command-line tool's output through `write`, and fixes what is safe to fix. Each message says what to do instead.
- **The job-postings sample from chapter 1**: <!-- claim: postings -->45 coded United States postings, the script that counts them, and a template for coding your own.
- **A harness inventory** (`node tools/harness-inventory.mjs <path>`): lists the evidence any repository's files give for each of the eight parts of a harness from chapter 4.
- **A week-one measurement** (chapter 31): `node tools/rework.mjs <path>` reads any repository's git history and shows, by folder, how often fixes landed on recent agent work and how long after the change, so you know where to look first. `node tools/rework-demo.mjs <folder>` builds a small history to try it on.
- **One command to set up and one to check** (chapter 5): `node setup.mjs` and `node check.mjs`, the same two commands CI runs.
- **An API contract generated from the code** (chapter 7): `contracts/openapi.json` comes from the Python models, the TypeScript client's types come from the contract, and `node check.mjs` fails if either falls behind.
- **A work list and a session log** (chapter 10): `progress/features.json` says what's done and what's next, each done item naming the test that proves it, and `progress/log.md` records what each session did and how it checked it. `node tools/progress.mjs` shows both.
- **A check on what the documentation claims** (chapter 8): `node tools/doc-claims.mjs` fails when a path this README or `AGENTS.md` names is gone, or when a number marked in them no longer matches the repository.
- **An instruction-file check** (chapter 6): `node tools/instruction-files.mjs <path>` reports what each instruction file puts in front of an agent at the start of a session, counting the files it imports, and flags a file over budget, an import that doesn't load, and a `CLAUDE.md` that hides an `AGENTS.md`.
- **Chapter 2's toys and tools**: a toy tokenizer and next-word model that show why token counts and answers vary, a cost calculator for conversations that resend their history, and a check that refuses to treat a refused or cut-off answer as finished.

Coming chapter by chapter: tools that change things, behind human approval; an MCP server; and evaluations.

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
