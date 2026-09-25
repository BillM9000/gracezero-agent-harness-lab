// Tests for tools/mutate.mjs (chapter 24). Each test builds a small git repository with one guarded
// function, its test and a list of mutations, runs the runner on it, and checks what it reports and
// that every file is put back.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { git as runGit } from "./git-run.mjs";

const RUNNER = join(dirname(fileURLToPath(import.meta.url)), "mutate.mjs");
const made = [];
after(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

const GUARD = "// Only even numbers pass.\nexport const isEven = (n) => n % 2 === 0;\n";
const TEST =
  'import assert from "node:assert/strict";\nimport { test } from "node:test";\nimport { isEven } from "./guard.mjs";\n' +
  'test("isEven", () => {\n  assert.equal(isEven(2), true);\n  assert.equal(isEven(3), false);\n});\n';

// Through tools/git-run.mjs: the machine's git setup stays out, and a failed call throws with
// everything git printed. Returns git's stdout.
function git(root, ...args) {
  return runGit(root, ["-c", "user.email=test@example.com", "-c", "user.name=test", ...args]);
}

// A committed repository whose tools/mutations.mjs holds the given entries.
function repository(mutations) {
  const root = mkdtempSync(join(tmpdir(), "mutate-"));
  made.push(root);
  mkdirSync(join(root, "tools"));
  writeFileSync(join(root, "guard.mjs"), GUARD);
  writeFileSync(join(root, "guard.test.mjs"), TEST);
  writeFileSync(join(root, "tools", "mutations.mjs"), `export const MUTATIONS = ${JSON.stringify(mutations, null, 2)};\n`);
  git(root, "init", "-q");
  git(root, "add", ".");
  git(root, "commit", "-q", "-m", "fixture");
  return root;
}

function mutate(root) {
  const result = spawnSync(process.execPath, [RUNNER, root], { encoding: "utf8" });
  return { code: result.status, output: result.stdout + result.stderr };
}

const RUN_TEST = { node: ["--test", "guard.test.mjs"] };
const clean = (root) => git(root, "status", "--porcelain", "--untracked-files=no").trim() === "";

test("a mutation the test notices is caught, and the file is put back", () => {
  const root = repository([{ guard: "evenness", file: "guard.mjs", find: "n % 2 === 0", replace: "true", run: RUN_TEST }]);
  const { code, output } = mutate(root);
  assert.equal(code, 0, output);
  assert.match(output, /caught {4}evenness/);
  assert.match(output, /1 of 1 mutations caught/);
  assert.equal(readFileSync(join(root, "guard.mjs"), "utf8"), GUARD);
  assert.ok(clean(root));
});

test("a mutation no test notices survives, and fails the run", () => {
  const root = repository([
    { guard: "the comment", file: "guard.mjs", find: "Only even numbers pass.", replace: "Anything passes.", run: RUN_TEST },
  ]);
  const { code, output } = mutate(root);
  assert.equal(code, 1);
  assert.match(output, /SURVIVED {2}the comment: nothing failed with it broken/);
  assert.ok(clean(root));
});

test("a mutation whose text is gone is stale, and fails the run", () => {
  const root = repository([{ guard: "old code", file: "guard.mjs", find: "n % 2 == 0", replace: "true", run: RUN_TEST }]);
  const { code, output } = mutate(root);
  assert.equal(code, 1);
  assert.match(output, /STALE {5}old code/);
});

test("a test command that fails on the unchanged code proves nothing, and fails the run", () => {
  const root = repository([
    { guard: "evenness", file: "guard.mjs", find: "n % 2 === 0", replace: "true", run: { node: ["--test", "missing.test.mjs"] } },
  ]);
  const { code, output } = mutate(root);
  assert.equal(code, 1);
  assert.match(output, /CONTROL {3}evenness: its test command doesn't pass on the unchanged code/);
  assert.equal(readFileSync(join(root, "guard.mjs"), "utf8"), GUARD);
});

test("test commands run without writing Python bytecode, so a file put back is never shadowed", () => {
  // The control passes only if the runner told Python not to write .pyc files.
  const needs = ["-e", 'process.exit(process.env.PYTHONDONTWRITEBYTECODE === "1" ? 0 : 1)'];
  const root = repository([{ guard: "the comment", file: "guard.mjs", find: "Only even", replace: "Any", run: { node: needs } }]);
  const { output } = mutate(root);
  assert.doesNotMatch(output, /CONTROL/);
  assert.match(output, /SURVIVED {2}the comment/);
  assert.ok(clean(root));
});

// The runner finds a stale entry only when it runs, which CI does every night. This finds one in
// seconds, in node check.mjs, so the list can't fall behind the code for a day. (Chapter 14's
// policy change made one entry stale, and only the nightly run noticed.)
test("every entry in the repository's own list changes text that is in its file exactly once", async () => {
  const root = join(dirname(RUNNER), "..");
  const { MUTATIONS } = await import(pathToFileURL(join(root, "tools", "mutations.mjs")).href);
  const stale = MUTATIONS.filter((m) => {
    const text = readFileSync(join(root, m.file), "utf8").replaceAll("\r\n", "\n");
    return text.split(m.find).length !== 2;
  }).map((m) => `${m.guard} (${m.file})`);
  assert.deepEqual(stale, []);
});

test("it refuses to start with uncommitted changes, and leaves them alone", () => {
  const root = repository([{ guard: "evenness", file: "guard.mjs", find: "n % 2 === 0", replace: "true", run: RUN_TEST }]);
  const edited = GUARD.replace("Only even numbers pass.", "Work in progress.");
  writeFileSync(join(root, "guard.mjs"), edited);
  const { code, output } = mutate(root);
  assert.equal(code, 2);
  assert.match(output, /refusing to start with uncommitted changes/);
  assert.equal(readFileSync(join(root, "guard.mjs"), "utf8"), edited);
});
