---
name: add-a-guard
description: Adds a guard to this repository the way its rules require, as a check whose failure says what to do, a test that plants the violation, and an entry in tools/mutations.mjs that breaks the guard. Use when asked to add a check, a rule, a lint, a policy or a guardrail here.
---

# Add a guard

<!-- The lab's own skill, and the filled example of templates/ship/skills/your-skill-name/SKILL.md.
node tools/kit.mjs skill .claude/skills/add-a-guard checks it. -->

## When it applies

When a rule kept in prose, a review comment or a mistake that keeps coming back should become a check in this repository. Not for changing what an existing check decides: rule 12 in `AGENTS.md` says to fix what a failing check reports, never to weaken the check.

## Steps

1. Write the check where its kind lives (the Layout table in `AGENTS.md`), with a failure message that says what's wrong, why it matters and what to do instead.
2. Write a test that plants the violation in a copy of what it checks and requires that failure and its message. Run it before the check exists, and see it fail for the right reason.
3. Add an entry to `tools/mutations.mjs` that breaks the guard, naming the test that must catch it (the shape is in the reference below), then run `node tools/mutate.mjs --only "GROUP:"` for its group.
4. If `node check.mjs` gains a check, list its files in `tools/protected.mjs` and update the marked count in `AGENTS.md`.
5. Record the change in `CHANGELOG.md`, in the same commit, and run `node check.mjs` until every check passes.

## References

- [The shape of a mutation entry, with one from the lab](references/mutation-entry.md)
