# Changelog

## 2026-09-22

- **Skeleton.** A helpdesk service in Python (FastAPI on SQLite) in three layers (routes, services, data) with one composition root, invented sample data, a deterministic mock model, a TypeScript client and command-line tool, and CI for both languages. Dependencies are pinned in `python/requirements-lock.txt` and `ts/package-lock.json`.
- **First guardrail.** Three import-linter contracts: the layers stay in order, routes never import the data layer directly, and the model package imports nothing else from the helpdesk. Each contract's name carries the fix, so the failure message tells whoever broke it what to do. `tests/guardrails/` plants each violation in a copy of the package and requires the matching failure; the unmodified copy is the control.
- **Found by the guardrail tests on their first run:** a layers contract alone does not stop a route importing the data layer, because it only forbids lower layers importing higher ones. The direct-import contract was added for that.
- **Found by treating warnings as errors:** the composition root opened a database connection that nothing closed. The app now closes it on shutdown, and the test run fails if it ever leaks again (checked by putting the leak back: pytest exits 1 with two unclosed-connection warnings).
- **Not yet run:** CI, because the repository has no remote yet. Everything above was run locally on Windows with Python 3.14.3 and Node 24.14.0. `pyproject.toml` declares Python 3.12 as the minimum, but nothing older than 3.14 has been run.
