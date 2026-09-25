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

function mutate(root, ...args) {
  const result = spawnSync(process.execPath, [RUNNER, root, ...args], { encoding: "utf8" });
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

// The nightly job runs every entry, and the list only grows, so a run can outgrow the job's timeout
// without any check failing (chapter 36). Nobody has timed the job on GitHub's runners yet, so this
// allows 5 minutes for setup and 7 seconds an entry: about twice the slowest rate seen on one
// Windows machine, 476 entries in 29.1 minutes. When it fails, raise the timeout.
test("the nightly job runs every entry, with a timeout that leaves room for them all", async () => {
  const root = join(dirname(RUNNER), "..");
  const { MUTATIONS } = await import(pathToFileURL(join(root, "tools", "mutations.mjs")).href);
  const workflow = readFileSync(join(root, ".github", "workflows", "nightly.yml"), "utf8").replaceAll("\r\n", "\n");
  const jobs = (workflow.split(/^jobs:\n/m)[1] ?? "").split(/^(?= {2}[\w-]+:\n)/m);
  const job = jobs.find((text) => /^ {6}- run: node tools\/mutate\.mjs$/m.test(text));
  assert.ok(job, "no job in .github/workflows/nightly.yml runs `node tools/mutate.mjs`, the whole list");
  const minutes = Number(job.match(/^ {4}timeout-minutes: (\d+)$/m)?.[1] ?? 0);
  const needed = Math.ceil((5 * 60 + MUTATIONS.length * 7) / 60);
  assert.ok(
    minutes >= needed,
    `nightly.yml's mutation job stops at ${minutes} minutes, and ${MUTATIONS.length} entries need about ${needed}. ` +
      "Raise its timeout-minutes, and say why in the comment above it.",
  );
});

// --only (chapter 24): one guard's entries, by the start of their names.
const TWO = [
  { guard: "evenness: two is even", file: "guard.mjs", find: "n % 2 === 0", replace: "true", run: RUN_TEST },
  { guard: "comment: says what passes", file: "guard.mjs", find: "Only even numbers pass.", replace: "Anything.", run: RUN_TEST },
];

test("--only runs just the entries whose name starts with it, and says how many of all it ran", () => {
  const root = repository(TWO);
  const { code, output } = mutate(root, "--only", "evenness:");
  assert.equal(code, 0, output);
  assert.match(output, /caught {4}evenness: two is even/);
  assert.doesNotMatch(output, /comment/);
  assert.match(output, /1 of 1 mutations caught in [\d.]+ min \(--only "evenness:": 1 of the 2 entries\)\./);
  assert.ok(clean(root));
});

test("--only can be given more than once, and the root can come after it", () => {
  const root = repository(TWO);
  const result = spawnSync(process.execPath, [RUNNER, "--only", "evenness:", "--only", "comment:", root], { encoding: "utf8" });
  const output = result.stdout + result.stderr;
  assert.equal(result.status, 1, output);
  assert.match(output, /caught {4}evenness/);
  assert.match(output, /SURVIVED {2}comment: says what passes/);
  assert.match(output, /1 of 2 mutations caught .*: 2 of the 2 entries\)/);
});

test("an --only that selects nothing refuses before anything runs, and lists the groups", () => {
  const root = repository(TWO);
  const { code, output } = mutate(root, "--only", "evennes:");
  assert.equal(code, 1);
  assert.match(output, /--only "evennes:" selects none of the 2 entries/);
  assert.match(output, /The groups: comment, evenness\./);
  assert.doesNotMatch(output, /caught|SURVIVED|CONTROL/);
  assert.equal(readFileSync(join(root, "guard.mjs"), "utf8"), GUARD);
});

test("one --only that selects nothing refuses the run, though another selects something", () => {
  const root = repository(TWO);
  const { code, output } = mutate(root, "--only", "evenness:", "--only", "coment:");
  assert.equal(code, 1);
  assert.match(output, /--only "coment:" selects none/);
  assert.doesNotMatch(output, /caught/);
});

test("--only without a prefix, or an option it doesn't know, is refused", () => {
  const root = repository(TWO);
  assert.match(mutate(root, "--only").output, /--only needs the start of an entry's name/);
  const unknown = mutate(root, "--all");
  assert.equal(unknown.code, 1);
  assert.match(unknown.output, /--all isn't an option/);
});

// --list (chapter 24): the entries and their groups, with nothing run or changed.
test("--list prints every entry and every group, runs nothing, and needs no clean tree", () => {
  const odd = { guard: "evenness: three is odd", file: "guard.mjs", find: "=== 0", replace: "!== 1", run: RUN_TEST };
  const root = repository([...TWO, odd]);
  const edited = GUARD.replace("Only even numbers pass.", "Work in progress.");
  writeFileSync(join(root, "guard.mjs"), edited);
  const { code, output } = mutate(root, "--list");
  assert.equal(code, 0, output);
  assert.deepEqual(output.trim().split("\n"), [
    "evenness: two is even  (guard.mjs)",
    "comment: says what passes  (guard.mjs)",
    "evenness: three is odd  (guard.mjs)",
    "",
    'The groups, and their entries; --only "GROUP:" runs one:',
    "  comment   1",
    "  evenness  2",
    "",
    "mutate --list: 3 entries in 2 groups. Nothing was run or changed.",
  ]);
  assert.equal(readFileSync(join(root, "guard.mjs"), "utf8"), edited);
  const one = mutate(root, "--list", "--only", "comment:");
  assert.equal(one.code, 0, one.output);
  assert.match(one.output, /^comment: says what passes {2}\(guard\.mjs\)$/m);
  assert.doesNotMatch(one.output, /evenness/);
  assert.match(one.output, /1 entry in 1 group \(--only "comment:": 1 of the 3 entries\)\. Nothing was run/);
  assert.match(mutate(root, "--list", "--only", "coment:").output, /--only "coment:" selects none of the 3 entries/);
});

test("--list on the lab's own list prints one line an entry", async () => {
  const root = join(dirname(RUNNER), "..");
  const { MUTATIONS } = await import(pathToFileURL(join(root, "tools", "mutations.mjs")).href);
  const { code, output } = mutate(root, "--list");
  assert.equal(code, 0, output);
  const entries = output.split("\n\n")[0].split("\n");
  assert.deepEqual(entries, MUTATIONS.map((m) => `${m.guard}  (${m.file})`));
  const groups = new Set(MUTATIONS.map((m) => m.guard.split(":")[0]));
  assert.match(output, new RegExp(`mutate --list: ${MUTATIONS.length} entries in ${groups.size} groups\\.`));
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
