// Tests for tools/feedback.mjs (chapter 25): what a failed check sends back to an agent.
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { failureReport, RERUN, RULES, runFastChecks } from "./feedback.mjs";

const made = [];
after(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

// A folder whose check.mjs prints the given lines and exits with the given code.
function project(lines, code) {
  const root = mkdtempSync(join(tmpdir(), "feedback-"));
  made.push(root);
  writeFileSync(join(root, "check.mjs"), `console.log(${JSON.stringify(lines.join("\n"))});\nprocess.exit(${code});\n`);
  return root;
}

const REPORT = [
  "PASS  Python lint (ruff check) (0.2s)",
  "FAIL  Agent definitions (python -m agent_policy) (0.3s)",
  "      agents/triage.toml: max_turns is 50, above the policy's limit of 10.",
  "PASS  Work list (tools/progress.mjs) (0.3s)",
  "",
  "1 of 3 checks failed.",
];

test("keeps the failing checks and their output, and leaves out the ones that passed", () => {
  const report = failureReport(REPORT.join("\r\n"));
  assert.match(report, /^FAIL {2}Agent definitions/);
  assert.match(report, /max_turns is 50, above the policy's limit of 10/);
  assert.match(report, /1 of 3 checks failed\.$/);
  assert.doesNotMatch(report, /PASS/);
});

test("cuts a long report and says how to see the rest", () => {
  const report = failureReport(`FAIL  Tests (9.0s)\n${"x".repeat(10000)}`, 500);
  assert.ok(report.length < 600, `the report is ${report.length} characters`);
  assert.match(report, /\[cut at 500 characters: run node check\.mjs --fast to see the rest\]$/);
});

test("the exit code decides whether the checks passed, not the words they print", () => {
  const passing = runFastChecks(project(["FAIL  a check that only says so"], 0));
  assert.equal(passing.passed, true);
  const failing = runFastChecks(project(["All 3 checks passed."], 1));
  assert.equal(failing.passed, false);
  assert.match(failing.output, /All 3 checks passed\./);
});

test("the rules say what doesn't count as a fix, and how to check one", () => {
  assert.equal(RERUN, "node check.mjs --fast");
  assert.match(RULES.join(" "), /Don't weaken or skip a test/);
  assert.match(RULES.join(" "), /stop and say why instead of changing it/);
});
