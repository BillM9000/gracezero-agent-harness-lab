# Handoff: 2026-09-30, a guard for the audit log's order

<!-- A filled example of templates/ship/handoff.md, for an illustrative session in this lab. The
commands are the lab's own. -->

## Done, with evidence

- The MCP front door records a request's attempt before the server acts on it, then its outcome: `python -m pytest tests/test_mcp_http.py -q` from `python/` (every test passed).
- Its planted breaks are caught: `node tools/mutate.mjs --only "front door:" --only "audit:"` (every entry caught).
- Everything else still passes: `node check.mjs` (every check passed).

## Not done

- `python -m mcp_governance audit` shows a request whose server never answered as "passed to the server, and no outcome was recorded", and nothing yet counts how often that happens.

## Next

1. Decide whether a request with no outcome should raise an alert, and record the decision as a gap.

## Known issues

- None seen in this session.
