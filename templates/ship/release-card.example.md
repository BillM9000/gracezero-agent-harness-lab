# Release card: the helpdesk 0.2.0

<!-- A filled example of templates/ship/release-card.md, for an illustrative release of the lab's
helpdesk; the commit id is a made-up one, and the people are the lab's invented staff. -->

## What ships

- The approval queue: F1 to F5 of `templates/agree/features.example.json`.
- Ids too big for SQLite count as missing (`templates/ship/change-record.example.md`).

## Gates, with evidence

| Gate | Evidence | Result |
|---|---|---|
| Every check | `node check.mjs` on the commit below | passed, on 2026-09-30 |
| The locked spec | `node tools/features-lock.mjs templates/agree/features.example.json` | passed, on 2026-09-30 |
| The promotion gate | `python -m helpdesk.gate check` | passed, on 2026-09-30 |
| A lead's approval | Dana Whitfield, below | signed, on 2026-09-30 |

## Risks and rollback

A proposal filed before the release and decided after it is decided by the new rules; there were none pending. To roll back, deploy the previous release's commit; the approval log keeps every record either way.

## Deploy declaration

- **Commit:** 0123456789abcdef0123456789abcdef01234567
- **Environment:** staging
- **Signed by:** Dana Whitfield, support lead
- **Signed at:** 2026-09-30 16:00, UTC
