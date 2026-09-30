// Tests for check.mjs itself (chapters 5, 20 and 24): the day its checks judge the models' retirement
// dates as of, and that it fails when a check fails. Each runs a copy of check.mjs in a planted folder
// whose "checks" are stand-ins: the Python tools are empty files that can't run, and the npm scripts
// print the AGENT_POLICY_TODAY they were given and fail, so check.mjs shows it in their output. Nothing
// here runs the lab's real checks.
// Run: node --test tools/check.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";

import { DATE_FILE, pinnedDay, VARIABLE } from "./policy-date.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const base = mkdtempSync(join(tmpdir(), "check-"));
after(() => rmSync(base, { recursive: true, force: true }));

const WINDOWS = process.platform === "win32";
const SCRIPTS = ["api-types", "typecheck", "lint", "deps", "test"];

let n = 0;
// A folder check.mjs takes for a set-up repository: its own copy, the policy-date module, a models
// file with the given contents, and stand-ins for everything its checks run.
function plant(models = "read = 2031-01-02\n") {
  const root = join(base, `case-${++n}`);
  const files = {
    [DATE_FILE]: models,
    [WINDOWS ? "python/.venv/Scripts/python.exe" : "python/.venv/bin/python"]: "",
    "ts/node_modules/.keep": "",
    "ts/package.json": JSON.stringify({ private: true, scripts: Object.fromEntries(SCRIPTS.map((s) => [s, "node day.mjs"])) }),
    "ts/day.mjs": `console.log("${VARIABLE}=" + process.env.${VARIABLE});\nprocess.exit(1);\n`,
  };
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  mkdirSync(join(root, "tools"));
  copyFileSync(join(ROOT, "check.mjs"), join(root, "check.mjs"));
  copyFileSync(join(ROOT, "tools", "policy-date.mjs"), join(root, "tools", "policy-date.mjs"));
  return root;
}

// Runs the planted check.mjs with the caller's AGENT_POLICY_TODAY set to `day`, or unset.
function check(root, args, day) {
  const env = { ...process.env };
  delete env[VARIABLE];
  // A node --test started by this test runner would inherit its context and skip its files.
  delete env.NODE_TEST_CONTEXT;
  if (day !== undefined) env[VARIABLE] = day;
  const run = spawnSync(process.execPath, ["check.mjs", ...args], { cwd: root, encoding: "utf8", env });
  return { status: run.status, output: `${run.stdout}${run.stderr}` };
}

test("every check runs as of the models file's read day, unless the caller sets AGENT_POLICY_TODAY", () => {
  const root = plant("source = \"a page\"\nread = 2031-01-02\n");
  const pinned = check(root, ["--fast"]);
  assert.match(pinned.output, /FAIL {2}TypeScript type-check/);
  assert.match(pinned.output, new RegExp(`${VARIABLE}=2031-01-02`));
  assert.doesNotMatch(pinned.output, new RegExp(`${VARIABLE}=(?!2031-01-02)`));
  const chosen = check(root, ["--fast"], "2032-03-04");
  assert.match(chosen.output, new RegExp(`${VARIABLE}=2032-03-04`));
  assert.doesNotMatch(chosen.output, /2031-01-02/);
});

// Chapter 35's second guardrail: the cheap checks in one command, and all of them in CI.
const SUITES = ["Python tests (pytest)", "TypeScript tests", "Script tests"];

test("a failing check fails the run, and --fast leaves out the three test suites and nothing else", () => {
  const root = plant();
  const listed = check(root, ["--list"]);
  assert.equal(listed.status, 0, listed.output);
  const labels = listed.output.trim().split(/\r?\n/);
  assert.ok(SUITES.every((suite) => labels.includes(suite)), listed.output);
  const ran = (output) => [...output.matchAll(/^(?:PASS|FAIL) {2}(.+) \(\d+\.\d+s\)$/gm)].map((m) => m[1]);
  const fast = check(root, ["--fast"]);
  assert.equal(fast.status, 1, fast.output);
  assert.deepEqual(ran(fast.output), labels.filter((label) => !SUITES.includes(label)));
  const cheap = labels.length - SUITES.length;
  assert.match(fast.output, new RegExp(`^${cheap} of ${cheap} checks failed \\(--fast: 3 test suites not run`, "m"));
  const full = check(root, []);
  assert.equal(full.status, 1, full.output);
  assert.deepEqual(ran(full.output), labels);
  assert.match(full.output, new RegExp(`^${labels.length} of ${labels.length} checks failed\\.$`, "m"));
});

test("CI runs the full set of checks, the same two commands a reader runs, on every change to code", () => {
  const text = readFileSync(join(ROOT, ".github", "workflows", "ci.yml"), "utf8").replaceAll("\r\n", "\n");
  const jobs = (text.split(/^jobs:\n/m)[1] ?? "").split(/^(?= {2}[\w-]+:\n)/m);
  const job = jobs.find((j) => /^ {6}- run: node check\.mjs/m.test(j));
  assert.ok(job, "no job in ci.yml runs node check.mjs");
  const runs = [...job.matchAll(/^ {6}- run: (.+)$/gm)].map((m) => m[1]);
  assert.deepEqual(runs, ["node setup.mjs", "node check.mjs"], "CI's check job must run setup, then every check");
  assert.match(job, /^ {4}runs-on: \$\{\{ matrix\.os \}\}$/m);
  // Readers' three systems, with the Python the lab is tested with (chapter 5).
  assert.match(job, /^ {8}os: \[ubuntu-latest, windows-latest, macos-latest\]$/m, "the check job must run on Linux, Windows and macOS");
  assert.match(job, /^ {10}python-version: \$\{\{ matrix\.python \}\}$/m, "setup-python must take the matrix's Python");
  // And the oldest Python the package declares, so the declaration is tested, not only written.
  const pyproject = readFileSync(join(ROOT, "python", "pyproject.toml"), "utf8");
  const oldest = /^requires-python = ">=(\d+\.\d+)"$/m.exec(pyproject)?.[1];
  assert.ok(oldest, "python/pyproject.toml declares no requires-python");
  assert.match(job, new RegExp(`^ {10}- os: ubuntu-latest\\n {12}python: "${oldest.replace(".", "\\.")}"$`, "m"), `no leg runs Python ${oldest}, the package's declared minimum`);
  // Every push to main and every pull request, skipping only a change to Markdown alone, which
  // docs.yml checks instead (tools/templates.test.mjs holds the two to the same paths).
  assert.match(text, /^ {2}push:\n {4}branches: \[main\]\n {4}paths-ignore: \["\*\*\.md"\]$/m);
  assert.match(text, /^ {2}pull_request:\n {4}paths-ignore: \["\*\*\.md"\]$/m);
});

test("a day that isn't YYYY-MM-DD, or a models file with no read day, stops the run before any check", () => {
  const wrong = check(plant(), ["--fast"], "tomorrow");
  assert.equal(wrong.status, 1, wrong.output);
  assert.match(wrong.output, /AGENT_POLICY_TODAY is "tomorrow"; set it to a day, such as 2027-04-01/);
  assert.match(wrong.output, /Nothing was checked\./);
  assert.doesNotMatch(wrong.output, /^(PASS|FAIL) /m);
  const undated = check(plant('source = "a page"\n'), ["--fast"]);
  assert.equal(undated.status, 1, undated.output);
  assert.match(undated.output, /python\/agents\/models\.toml has no "read = YYYY-MM-DD" line/);
  assert.doesNotMatch(undated.output, /^(PASS|FAIL) /m);
});

// The models file has a section a provider, each read on its own day (chapter 18's second provider).
// The pinned day is the latest: by then every provider's dates had been copied.
test("with a read day in each provider's section, the checks run as of the latest", () => {
  const root = plant('[one]\nsource = "a page"\nread = 2031-01-02\n\n[another]\nsource = "another page"\nread = 2030-05-06\n');
  const pinned = check(root, ["--fast"]);
  assert.match(pinned.output, new RegExp(`${VARIABLE}=2031-01-02`));
  assert.doesNotMatch(pinned.output, /2030-05-06/);
  const reversed = plant('[one]\nread = 2030-05-06\n\n[another]\nread = 2031-01-02\n');
  assert.match(check(reversed, ["--fast"]).output, new RegExp(`${VARIABLE}=2031-01-02`));
});

test("the lab's checks run as of the latest day a provider's section of python/agents/models.toml was read", () => {
  const text = readFileSync(join(ROOT, DATE_FILE), "utf8");
  const read = [...text.matchAll(/^read = (\d{4}-\d{2}-\d{2})$/gm)].map((m) => m[1]).sort();
  assert.ok(read.length >= 2, `${DATE_FILE} has fewer than two read lines, one a provider`);
  assert.equal(pinnedDay(ROOT), read.at(-1));
});

// The nightly job exists to notice a retirement the day its notice window opens, so it must not
// inherit the pinned day: it runs python -m agent_policy itself, never through check.mjs.
test("the nightly retirement job checks as of today, never a pinned day", () => {
  const text = readFileSync(join(ROOT, ".github", "workflows", "nightly.yml"), "utf8").replaceAll("\r\n", "\n");
  const code = (block) => block.split("\n").filter((line) => line.trim() && !line.trim().startsWith("#")).join("\n");
  const jobs = (text.split(/^jobs:\n/m)[1] ?? "").split(/^(?= {2}[\w-]+:\n)/m);
  const retirement = jobs.find((job) => /-m agent_policy\b/.test(code(job)));
  assert.ok(retirement, "nightly.yml has no job that runs python -m agent_policy");
  assert.doesNotMatch(code(retirement), /--today|check\.mjs/, "the retirement job must run python -m agent_policy as of today");
  assert.doesNotMatch(code(text), new RegExp(VARIABLE), `nightly.yml must not set ${VARIABLE}: the retirement job checks as of today`);
});
