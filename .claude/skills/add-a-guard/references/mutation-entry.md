# The shape of a mutation entry

Each entry in `tools/mutations.mjs` names the guard, the file, the exact text to change, what to change it to, and the test command that must then fail. `node tools/mutate.mjs` first runs the command on the unchanged code, which must pass, then makes the change, requires the command to fail, and puts the file back.

```js
{
  guard: "check: a failing check fails the run",
  file: "check.mjs",
  find: "process.exit(failed ? 1 : 0);",
  replace: "process.exit(0);",
  run: checkTest("a failing check fails the run"),
},
```

- `guard` starts with its group and a colon, so `node tools/mutate.mjs --only "check:"` runs the group, and `--list` shows every group.
- `find` must be in the file exactly once, or the entry is stale and fails the run.
- `run` is `pytest(...)` for a Python test, `vitest(file, name)` for a TypeScript one, or `nodeTest(file, name)` for a Node script's test. Name the one test that should catch the break, so the run stays quick.
- Break the guard, not the test: the change makes the guard stop guarding, and the test is what has to notice.
