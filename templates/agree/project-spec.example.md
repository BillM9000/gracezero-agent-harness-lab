# Project spec: the approval queue

<!-- A filled example of templates/agree/project-spec.md, for the request in
templates/ask/intake-brief.example.md. The request is illustrative; what it describes is the lab's
own approval queue (chapter 19), and every test named in features.example.json is a real one. -->

**Version:** 1.0, 2026-09-30. **Owner:** Dana Whitfield.

## What it is

The triage assistant may propose a reply or a ticket's closing, and a member of staff approves or rejects each proposal in one step. Nothing changes until someone approves; every step, refusals included, is recorded with the change it made.

## Who it's for

Support staff, who approve replies on their own tickets, and leads, who approve closings and answer for what the helpdesk tells customers.

## Sources of truth, in order

1. The helpdesk's database, for tickets, staff and proposals.
2. `python/agents/policy.toml`, for which tools change things and the least approval each needs.
3. `templates/ask/gaps.example.json`, for what was decided and by whom.

## Hard rules

- The assistant never changes a ticket itself: its tools file proposals (`tests/test_approvals.py`).
- Nothing it can reach sends anything outside the helpdesk (`tests/fitness/test_nothing_sends_outside.py`).

## Out of scope

- Email or chat outside the helpdesk (G6).
- Proposals that expire on their own (G2).

## Order of work

1. F1, a reply waits for approval.
2. F2, closing needs a lead.
3. F3, a rejection's reason reaches the assistant.
4. F4, every step is recorded.

## Decisions

| Date | Decision | Decided by | Gap |
|---|---|---|---|
| 2026-09-30 | Only a lead approves closing a ticket; staff approve replies on their own tickets. | Dana Whitfield | G1 |
| 2026-09-30 | An undecided proposal waits, and nothing expires. | Dana Whitfield | G2 |
| 2026-09-30 | A rejection needs a reason, which the assistant reads word for word. | Dana Whitfield | G3 |
| 2026-09-30 | The first of two decisions at once wins; the second is refused and recorded. | Sam Rivera | G4 |
| 2026-09-30 | The policy sets each tool's least approval; a definition may ask for more. | Alex Moreno | G5 |
| 2026-09-30 | No direct email to customers, however urgent. | Dana Whitfield | G6 |
