// Break each guard on purpose and require a test to fail: node tools/mutate.mjs [root]
// [--only PREFIX]... [--list]
//
// Every chapter from 16 on checked its guards this way by hand before it was written: change one
// line so a guard stops guarding, run the test that should notice, and put the line back. This
// runs that list, tools/mutations.mjs, on demand; CI runs it every night (chapter 24), because it
// takes minutes, not seconds.
//
// Each test command first runs on the unchanged code, as the control, and must pass: a command
// that fails anyway, because of a typo in a test name, say, would otherwise count as catching
// every mutation given to it. Then the mutation is applied and the command must fail. A mutation
// survives when the command passes anyway: the guard can break without any test noticing. It is
// stale when its text is no longer in the file: the list has fallen behind the code. Survivors,
// stale entries and failed controls all fail the run.
//
// It refuses to start unless the tracked files are unchanged, puts back every file it touches
// even when a command throws, and checks the tree is unchanged again at the end.
//
// --only PREFIX runs only the entries whose name starts with PREFIX, such as "guard:" for the
// destructive-command guard (chapter 35 names one or two for each of its ten guardrails). It can be
// given more than once. A prefix that selects no entry refuses the run before anything changes: a
// mistyped prefix would otherwise check nothing and report every mutation caught (chapter 16).
//
// --list prints the entries, each with the file it breaks, then the groups, each with how many
// entries it has, and runs and changes nothing, so it works on a tree with uncommitted changes too.
// With --only it lists what that run would run.
//
// Exit codes: 0 every mutation caught (or listed), 1 something above went wrong, or an --only that
// selects nothing, 2 refused (uncommitted changes), 3 a file was not put back.
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// The arguments: an optional root, any number of --only PREFIX, and --list.
const only = [];
let rootArg;
let list = false;
for (let i = 2; i < process.argv.length; i++) {
  const arg = process.argv[i];
  if (arg === "--only") {
    const prefix = process.argv[++i];
    if (!prefix) {
      console.error("mutate: --only needs the start of an entry's name, such as --only \"guard:\".");
      process.exit(1);
    }
    only.push(prefix);
  } else if (arg === "--list") {
    list = true;
  } else if (arg.startsWith("--")) {
    console.error(`mutate: ${arg} isn't an option. Usage: node tools/mutate.mjs [root] [--only PREFIX]... [--list]`);
    process.exit(1);
  } else {
    rootArg = arg;
  }
}
const ROOT = resolve(rootArg ?? join(dirname(fileURLToPath(import.meta.url)), ".."));
const WINDOWS = process.platform === "win32";

// Node's test runner sets NODE_TEST_CONTEXT for the processes it starts, and a `node --test` that
// inherits it skips its test files with a warning and exits 0. Each command run here has to answer
// for itself, so the variable is removed. (This runner's own tests found it.)
const ENV = { ...process.env };
delete ENV.NODE_TEST_CONTEXT;
// Python checks a cached .pyc against its source's modification time, in whole seconds, and its
// size. A mutation that keeps the line's length ("forbid" to "ignore"), put back within the second,
// leaves a .pyc of the broken code that Python then trusts, so a later command would run it and a
// survivor could pass as caught. With no .pyc written, every run compiles the source on disk.
// (Found verifying chapter 22 from a fresh clone, where exactly that happened to a Try it step.)
ENV.PYTHONDONTWRITEBYTECODE = "1";

function changedFiles() {
  return spawnSync("git", ["status", "--porcelain", "--untracked-files=no"], { cwd: ROOT, encoding: "utf8" })
    .stdout.trim();
}

// A mutation's run is { python: [...] } for the lab's Python, { vitest: [...] } for the TypeScript
// tests, or { node: [...] } for a Node script, each with an optional cwd relative to the root.
function run(spec) {
  const cwd = join(ROOT, spec.cwd ?? ".");
  let program = process.execPath;
  let args = spec.node;
  if (spec.python) {
    program = join(ROOT, "python", ".venv", WINDOWS ? "Scripts/python.exe" : "bin/python");
    args = spec.python;
  } else if (spec.vitest) {
    args = [join(ROOT, "ts", "node_modules", "vitest", "vitest.mjs"), "run", ...spec.vitest];
  }
  const result = spawnSync(program, args, { cwd, encoding: "utf8", env: ENV });
  // No exit status means the command never ran, which proves nothing either way.
  return result.error || result.status === null ? "error" : result.status === 0 ? "pass" : "fail";
}

// Listing changes nothing, so it needs no clean tree.
const dirty = list ? "" : changedFiles();
if (dirty) {
  console.error(`mutate: refusing to start with uncommitted changes, because it rewrites files:\n${dirty}`);
  process.exit(2);
}

const { MUTATIONS: ALL } = await import(pathToFileURL(join(ROOT, "tools", "mutations.mjs")).href);
// Every prefix must select something, or the run would check less than it was asked to.
const empty = only.filter((prefix) => !ALL.some((m) => m.guard.startsWith(prefix)));
if (empty.length) {
  const groups = [...new Set(ALL.map((m) => m.guard.split(":")[0]))].sort((a, b) => a.localeCompare(b));
  console.error(
    `mutate: --only ${empty.map((p) => JSON.stringify(p)).join(", ")} selects none of the ${ALL.length} ` +
      "entries in tools/mutations.mjs, so nothing would be checked. Nothing ran.\n" +
      `Each entry's name starts with its group and a colon. The groups: ${groups.join(", ")}.`,
  );
  process.exit(1);
}
const MUTATIONS = only.length ? ALL.filter((m) => only.some((prefix) => m.guard.startsWith(prefix))) : ALL;
const selected = only.length
  ? ` (--only ${only.map((p) => JSON.stringify(p)).join(", ")}: ${MUTATIONS.length} of the ${ALL.length} entries)`
  : "";

if (list) {
  for (const m of MUTATIONS) console.log(`${m.guard}  (${m.file})`);
  const counts = new Map();
  for (const m of MUTATIONS) {
    const group = m.guard.split(":")[0];
    counts.set(group, (counts.get(group) ?? 0) + 1);
  }
  const groups = [...counts].sort(([a], [b]) => a.localeCompare(b));
  const width = Math.max(...groups.map(([group]) => group.length));
  console.log(`\nThe groups, and their entries; --only "GROUP:" runs one:`);
  for (const [group, n] of groups) console.log(`  ${group.padEnd(width)}  ${n}`);
  const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const listed = `${count(MUTATIONS.length, "entry", "entries")} in ${count(groups.length, "group", "groups")}`;
  console.log(`\nmutate --list: ${listed}${selected}. Nothing was run or changed.`);
  // Node writes to a pipe asynchronously on Linux and macOS, and process.exit() before a write
  // completes drops what's left (Node's documentation of process.stdout), which cut a long list
  // short on CI's Linux runner once. So wait until it has all gone.
  await new Promise((resolve) => process.stdout.write("", resolve));
  process.exit(0);
}

const started = Date.now();
const controls = new Map();
const failures = [];
for (const m of MUTATIONS) {
  const key = JSON.stringify(m.run);
  if (!controls.has(key)) controls.set(key, run(m.run));
  if (controls.get(key) !== "pass") {
    console.log(`CONTROL   ${m.guard}: its test command doesn't pass on the unchanged code`);
    failures.push(m.guard);
    continue;
  }
  const path = join(ROOT, m.file);
  const original = readFileSync(path, "utf8");
  const eol = original.includes("\r\n") ? "\r\n" : "\n";
  const text = original.replaceAll("\r\n", "\n");
  if (text.split(m.find).length !== 2) {
    console.log(`STALE     ${m.guard}: the text to change isn't in ${m.file} exactly once`);
    failures.push(m.guard);
    continue;
  }
  writeFileSync(path, text.replace(m.find, m.replace).replaceAll("\n", eol));
  let outcome;
  try {
    outcome = run(m.run);
  } finally {
    writeFileSync(path, original);
  }
  if (outcome === "fail") {
    console.log(`caught    ${m.guard}`);
  } else {
    console.log(`${outcome === "pass" ? "SURVIVED " : "ERROR    "} ${m.guard}: ${outcome === "pass" ? "nothing failed with it broken" : "its test command didn't run"}`);
    failures.push(m.guard);
  }
}
const minutes = ((Date.now() - started) / 60000).toFixed(1);
console.log(`\nmutate: ${MUTATIONS.length - failures.length} of ${MUTATIONS.length} mutations caught in ${minutes} min${selected}.`);

const left = changedFiles();
if (left) {
  console.error(`mutate: these files were not put back:\n${left}`);
  process.exit(3);
}
process.exit(failures.length ? 1 : 0);
