# Contributing

Issues and pull requests are welcome: a check that passes when it shouldn't, a Try it step that doesn't print what its chapter says, a command that fails on your system, or a guard the lab is missing. For a security problem, don't open an issue; see `SECURITY.md`.

## Before you open a pull request

1. Run `node setup.mjs`, then `node check.mjs`, and see every check pass before you change anything.
2. Make the change. The rules are in `AGENTS.md`, the same ones any coding agent here follows: the layers, the one door to the model, what's generated and must be regenerated rather than edited.
3. Prove it. A change in behavior comes with a test that fails without it. A new guard comes with a test that plants the violation it catches, and an entry in `tools/mutations.mjs` that breaks the guard; run `node tools/mutate.mjs --only "GROUP:"` for its group. `.claude/skills/add-a-guard/` walks through it.
4. Record it. Add an entry at the top of `CHANGELOG.md` in the same commit, as `templates/ship/CHANGELOG-convention.md` describes: what changed, why, and how you checked it.
5. Run `node check.mjs` again, and open the pull request. CI runs the same checks on Linux, Windows and macOS.

## What a pull request mustn't do

- Weaken, skip or delete a check, a test or a rule to get a pass. If a check is wrong, say why in the pull request, and change it on its own, with its test.
- Edit a generated file by hand: `contracts/openapi.json` and `ts/src/api-types.ts` come from the code (`node tools/regenerate.mjs`).
- Change the codes or counts in `postings/sample-2026-09-22.json`. It's a dated record of what the postings said on the day they were read.
- Add a secret, a key or a token, even a fake-looking one.

The chapters' tags (`ch01` to `ch36`, `appB`) are part of the book's record, and are only moved by the maintainer; a fix lands on `main`.

## License

By contributing, you agree that your contribution is licensed under the repository's MIT license (`LICENSE`).
