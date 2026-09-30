# Change record: ids too big for SQLite count as missing

<!-- A filled example of templates/ship/change-record.md, for a real change to this lab (chapter 3's
20-digit ticket number); the people are the lab's invented staff. -->

**Date:** 2026-09-30. **Owner:** Sam Rivera. **Kind:** normal.

## What

`python/src/helpdesk/data/repository.py`: a lookup by a ticket, customer, staff or proposal id that SQLite can't store (more than 8 bytes) finds nothing, instead of raising `OverflowError`.

## Why

A 20-digit ticket number passed the tool's schema and ended the triage assistant's run with an `OverflowError`; over HTTP the same number was a 500.

## Impact

Any code that looks a row up by id. A number that big was never a real row, so nothing that worked before changes; a caller that relied on the error would now get "doesn't exist".

## Dry run

`python -m pytest -q` from `python/` on a copy of the branch: every test passed, and the new tests failed with the change taken out.

## Rollback

Revert the commit. Nothing is stored differently, so no data needs putting back.

## Gates

- `node check.mjs`: all checks passed.
- `node tools/mutate.mjs --only "data:"`: every planted break caught.
- Reviewed and approved by Dana Whitfield.
