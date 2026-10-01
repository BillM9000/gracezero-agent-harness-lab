// Tests for tools/weekly.mjs (chapter 31). Each test runs the script as gh's output would reach it,
// as JSON on standard input, with runs the test writes, and checks what it prints.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "weekly.mjs");

// What the script prints for this input; it throws, with the exit status and stderr, if it fails.
function weekly(input, ...args) {
  const text = typeof input === "string" ? input : JSON.stringify(input);
  return execFileSync(process.execPath, [SCRIPT, ...args], { input: text, encoding: "utf8", stdio: "pipe" });
}

// One run as gh run list --json conclusion,createdAt,headBranch writes it.
const run = (createdAt, conclusion, headBranch = "main") => ({ conclusion, createdAt, headBranch });

// The week of Monday 2026-09-21 runs from that Monday to Sunday 2026-09-27, in UTC.
test("a cancelled and a skipped run are left out of both counts", () => {
  const runs = [
    run("2026-09-22T10:00:00Z", "success"),
    run("2026-09-22T11:00:00Z", "failure"),
    run("2026-09-23T10:00:00Z", "cancelled"),
    run("2026-09-23T11:00:00Z", "skipped"),
  ];
  assert.equal(weekly(runs), "2026-09-21  1 of 2 failed (50%)\n");
});

test("failure, timed_out and startup_failure each count as a failure, and success as a run", () => {
  const runs = [
    run("2026-09-08T10:00:00Z", "failure"),
    run("2026-09-08T11:00:00Z", "success"),
    run("2026-09-15T10:00:00Z", "timed_out"),
    run("2026-09-15T11:00:00Z", "success"),
    run("2026-09-22T10:00:00Z", "startup_failure"),
    run("2026-09-22T11:00:00Z", "success"),
  ];
  assert.equal(
    weekly(runs),
    "2026-09-07  1 of 2 failed (50%)\n2026-09-14  1 of 2 failed (50%)\n2026-09-21  1 of 2 failed (50%)\n",
  );
});

test("a Sunday run lands in the week of the Monday six days before it, and the Monday after starts a new week", () => {
  const runs = [run("2026-09-27T23:59:00Z", "failure"), run("2026-09-28T00:00:00Z", "success")];
  assert.equal(weekly(runs), "2026-09-21  1 of 1 failed (100%)\n2026-09-28  0 of 1 failed (0%)\n");
  // A run in the middle of the week goes back to its Monday too.
  assert.equal(weekly([run("2026-09-30T12:00:00Z", "success")]), "2026-09-28  0 of 1 failed (0%)\n");
});

test("percentages round to whole numbers", () => {
  const third = [run("2026-09-21T10:00:00Z", "failure"), run("2026-09-21T11:00:00Z", "success"), run("2026-09-21T12:00:00Z", "success")];
  assert.equal(weekly(third), "2026-09-21  1 of 3 failed (33%)\n");
  const twoThirds = [run("2026-09-28T10:00:00Z", "failure"), run("2026-09-28T11:00:00Z", "failure"), run("2026-09-28T12:00:00Z", "success")];
  assert.equal(weekly(twoThirds), "2026-09-28  2 of 3 failed (67%)\n");
});

test("weeks print oldest first, whatever order the runs come in", () => {
  // gh lists the newest run first.
  const runs = [
    run("2026-09-29T10:00:00Z", "success"),
    run("2026-09-15T10:00:00Z", "failure"),
    run("2026-09-22T10:00:00Z", "success"),
  ];
  assert.equal(
    weekly(runs),
    "2026-09-14  1 of 1 failed (100%)\n2026-09-21  0 of 1 failed (0%)\n2026-09-28  0 of 1 failed (0%)\n",
  );
});

test("--branch main drops a run on another branch", () => {
  const runs = [run("2026-09-22T10:00:00Z", "success", "main"), run("2026-09-22T11:00:00Z", "failure", "fix-the-form")];
  assert.equal(weekly(runs), "2026-09-21  1 of 2 failed (50%)\n");
  assert.equal(weekly(runs, "--branch", "main"), "2026-09-21  0 of 1 failed (0%)\n");
});

test("empty input, [], prints nothing and exits 0", () => {
  assert.equal(weekly([]), "");
});

test("input that isn't JSON exits non-zero with a message", () => {
  assert.throws(
    () => weekly("this is not JSON"),
    (error) => error.status !== 0 && /SyntaxError: .*is not valid JSON/.test(error.stderr),
  );
});

test("an option it doesn't know, or --branch without a name, exits non-zero, so a typo can't count every branch", () => {
  assert.throws(() => weekly([], "--brnach", "main"), (error) => error.status !== 0 && /Unknown option '--brnach'/.test(error.stderr));
  assert.throws(() => weekly([], "--branch"), (error) => error.status !== 0 && /'--branch <value>' argument missing/.test(error.stderr));
});
