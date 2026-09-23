# Changelog

## 2026-09-27, CI on request

- **`ci.yml` can be run on request** (`workflow_dispatch`; `gh workflow run ci.yml`), from this history's second commit, so CI can be run at any tag. It skips a push that changes only Markdown, which runs `docs.yml` instead (chapter 24), and a run on request covers that case.

## 2026-09-24, the guardrail tests read lint-imports in the encoding they ask it to write

- **The guardrail tests no longer depend on the shell's encoding.** Found verifying chapter 20: with `PYTHONIOENCODING=utf-8` set, as some shells set it, `tests/guardrails/test_layers_contract.py` gave 12 failed and 12 errors on Windows (unset, or set to `cp1252`, 12 passed), because `run_guardrail` read lint-imports' output with `text=True`, in the locale's code page, while lint-imports wrote its box-drawing characters in UTF-8. The test now sets `PYTHONIOENCODING=utf-8` in lint-imports' environment and reads its output as UTF-8, so both ends agree whatever the shell says. A new test runs the guardrail with the variable unset and set to `utf-8`, `cp1252` and `utf-16`: remove the setting from lint-imports' environment and the `cp1252` and `utf-16` cases fail (1 failed and 1 error, checked on Windows), because lint-imports then writes in whatever the shell set while the test reads UTF-8. The variable decides what lint-imports writes on every platform, so those two cases should fail anywhere; only Windows has run them. 16 tests in the file now, and all 16 pass with the variable unset and set to each of the three.

## 2026-09-22, chapter 1 lab

- **The job-postings sample.** `postings/sample-2026-09-22.json` is a byte-for-byte copy of the author's research record: 33 coded postings and 16 exclusions, read on 2026-09-22. `postings/tally.mjs` counts it and prints the same counts as the research script (checked by diffing the two outputs).
- **The tally now checks its input before counting anything.** It refuses a missing or non-boolean field, an unknown job type, a duplicate id and a few other slips, lists every problem at once, and names the posting, the field and the fix, quoting the codebook where it has an entry. `postings/tally.test.mjs` plants each problem in a copy of the sample (checked by switching the checks off: 5 of 7 tests fail).
- **A template for readers**, `postings/my-postings.template.json`, with the codebook and one placeholder posting. It tallies as shipped.
- **CI** runs the postings tests in a third job. Not yet run, for the same reason as below.

## 2026-09-22

- **Skeleton.** A helpdesk service in Python (FastAPI on SQLite) in three layers (routes, services, data) with one composition root, invented sample data, a deterministic mock model, a TypeScript client and command-line tool, and CI for both languages. Dependencies are pinned in `python/requirements-lock.txt` and `ts/package-lock.json`.
- **First guardrail.** Three import-linter contracts: the layers stay in order, routes never import the data layer directly, and the model package imports nothing else from the helpdesk. Each contract's name carries the fix, so the failure message tells whoever broke it what to do. `tests/guardrails/` plants each violation in a copy of the package and requires the matching failure; the unmodified copy is the control.
- **Found by the guardrail tests on their first run:** a layers contract alone does not stop a route importing the data layer, because it only forbids lower layers importing higher ones. The direct-import contract was added for that.
- **Found by treating warnings as errors:** the composition root opened a database connection that nothing closed. The app now closes it on shutdown, and the test run fails if it ever leaks again (checked by putting the leak back: pytest exits 1 with two unclosed-connection warnings).
- **Not yet run:** CI, because the repository has no remote yet. Everything above was run locally on Windows with Python 3.14.3 and Node 24.14.0. `pyproject.toml` declares Python 3.12 as the minimum, but nothing older than 3.14 has been run.
