// One command to run every check in the repository: node check.mjs
//
// Runs the Python lint, format, import-rule, model-text-rule, agent-policy, MCP-catalog, retrieval
// and test checks, a check that the API contract and the TypeScript types generated from it are
// current, the TypeScript type-check, import rules and tests, the Node script tests, a check that setup.mjs's
// Windows path limit still fits the installed packages, a check that every pinned package has its
// hashes and that what's installed matches the lock files, a budget for the instruction files, a check
// of what the documentation claims, and a check that the work list's done items name real tests,
// then prints one line per check. Exits 1 if any fails, after printing the end of that check's
// output. CI runs this same command.
//
// node check.mjs --list prints the checks' names and runs nothing.
// node check.mjs --fast skips the three test suites and runs the rest, the tier cheap enough to
// run after every edit (chapter 24). The full run is still what counts: CI runs it.
//
// The checks judge the models' retirement dates as of one day, the "read" date in
// python/agents/models.toml, so they pass or fail the same way on any date (tools/policy-date.mjs).
// Set AGENT_POLICY_TODAY=YYYY-MM-DD to check as of another day. python -m agent_policy on its own,
// and the nightly workflow's retirement job, check as of today.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { checkEnvironment } from "./tools/policy-date.mjs";

const ROOT = dirname(fileURLToPath(import.meta.url));
const WINDOWS = process.platform === "win32";
const BIN = join(ROOT, "python", ".venv", WINDOWS ? "Scripts" : "bin");
const tool = (name) => join(BIN, WINDOWS ? `${name}.exe` : name);

const python = join(ROOT, "python");
// Marks a test suite. Suites take most of the run's time, so --fast leaves them out.
const SUITE = "suite";
const CHECKS = [
  ["Python lint (ruff check)", tool("ruff"), ["check", "."], { cwd: python }],
  ["Python format (ruff format --check)", tool("ruff"), ["format", "--check", "."], { cwd: python }],
  ["Python import rules (lint-imports)", tool("lint-imports"), [], { cwd: python }],
  // The lab's own lint rule (chapter 17): a model's text is read through final_text.
  ["Python model-text rule (python -m helpdesk_lint)", tool("python"), ["-m", "helpdesk_lint"], { cwd: python }],
  // Agent definitions against the platform's policy (chapter 18).
  ["Agent definitions (python -m agent_policy)", tool("python"), ["-m", "agent_policy"], { cwd: python }],
  // The catalog of approved MCP servers against its rules (chapter 13).
  ["MCP server catalog (python -m mcp_governance)", tool("python"), ["-m", "mcp_governance"], { cwd: python }],
  // Retrieval against its golden set (chapter 9): recall at 3 at or above the floor in
  // evals/kb_questions.json, and nothing returned for questions the knowledge base can't answer.
  ["Knowledge-base retrieval (python -m helpdesk.kb eval)", tool("python"), ["-m", "helpdesk.kb", "eval"], { cwd: python }],
  // The contract is generated from the Python code, and the TypeScript types from the contract.
  // These two run before the type-check, so drift is reported as drift before it shows up as type errors.
  ["API contract (python -m helpdesk.contract)", tool("python"), ["-m", "helpdesk.contract", "check", "../contracts/openapi.json"], { cwd: python }],
  ["Python tests (pytest)", tool("python"), ["-m", "pytest", "-q", "-p", "no:cacheprovider"], { cwd: python }, SUITE],
  // npm is a .cmd script on Windows, which Node only runs through a shell. The commands are fixed text.
  ["TypeScript API types (npm run api-types)", "npm run api-types -- --check", [], { cwd: join(ROOT, "ts"), shell: true }],
  ["TypeScript type-check", "npm run typecheck", [], { cwd: join(ROOT, "ts"), shell: true }],
  // ESLint checks one file at a time; dependency-cruiser checks the rules between files (chapter 16).
  ["TypeScript import rules (eslint)", "npm run lint", [], { cwd: join(ROOT, "ts"), shell: true }],
  ["TypeScript dependency rules (dependency-cruiser)", "npm run deps", [], { cwd: join(ROOT, "ts"), shell: true }],
  ["TypeScript tests", "npm test", [], { cwd: join(ROOT, "ts"), shell: true }, SUITE],
  [
    "Script tests",
    process.execPath,
    [
      "--test",
      "postings/tally.test.mjs",
      "tools/harness-inventory.test.mjs",
      "tools/install-paths.test.mjs",
      "tools/lockfiles.test.mjs",
      "tools/instruction-files.test.mjs",
      "tools/doc-claims.test.mjs",
      "tools/progress.test.mjs",
      "tools/mutate.test.mjs",
      "tools/feedback.test.mjs",
      "tools/hooks/stop-check.test.mjs",
      "tools/hooks/destructive-guard.test.mjs",
      "tools/fix-loop.test.mjs",
      "tools/rework.test.mjs",
      "tools/protected.test.mjs",
      "tools/git-run.test.mjs",
      "tools/check.test.mjs",
    ],
    { cwd: ROOT },
    SUITE,
  ],
  ["Setup's path limit (tools/install-paths.mjs)", process.execPath, ["tools/install-paths.mjs"], { cwd: ROOT }],
  // Every pin has its hashes, setup requires them, and what's installed is what the locks say (chapter 20).
  ["Lock files (tools/lockfiles.mjs)", process.execPath, ["tools/lockfiles.mjs"], { cwd: ROOT }],
  // The lab's own budget for what its instruction files load: 200 lines, Claude Code's documented
  // target, and 4,000 estimated tokens, so long lines can't hide inside the line count.
  ["Instruction files (tools/instruction-files.mjs)", process.execPath, ["tools/instruction-files.mjs", ".", "--max-tokens", "4000"], { cwd: ROOT }],
  ["Documentation claims (tools/doc-claims.mjs)", process.execPath, ["tools/doc-claims.mjs", "."], { cwd: ROOT }],
  // Every item marked done names a test that exists; the Python and script tests above run them.
  ["Work list (tools/progress.mjs)", process.execPath, ["tools/progress.mjs", "."], { cwd: ROOT }],
];

if (process.argv.includes("--list")) {
  for (const [label] of CHECKS) console.log(label);
  process.exit(0);
}

const missing = [];
if (!existsSync(tool("python"))) missing.push("python/.venv");
if (!existsSync(join(ROOT, "ts", "node_modules"))) missing.push("ts/node_modules");
if (missing.length) {
  console.error(`Not set up yet (missing ${missing.join(" and ")}). Run node setup.mjs first.`);
  process.exit(1);
}

// Every check runs with AGENT_POLICY_TODAY set: the caller's day, or the one the repository records.
let CHECK_ENV;
try {
  CHECK_ENV = checkEnvironment(ROOT);
} catch (error) {
  console.error(`${error.message} Nothing was checked.`);
  process.exit(1);
}

const fast = process.argv.includes("--fast");
const selected = CHECKS.filter(([, , , , kind]) => !(fast && kind === SUITE));
let failed = 0;
for (const [label, command, args, options] of selected) {
  const started = Date.now();
  const run = spawnSync(command, args, { encoding: "utf8", env: CHECK_ENV, ...options });
  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  const ok = run.status === 0;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label} (${seconds}s)`);
  if (!ok) {
    failed++;
    const output = `${run.stdout ?? ""}${run.stderr ?? ""}${run.error ? run.error.message : ""}`.trimEnd();
    console.log(output.split("\n").slice(-25).map((line) => `      ${line}`).join("\n"));
  }
}
const skipped = CHECKS.length - selected.length;
const note = skipped ? ` (--fast: ${skipped} test suites not run; run node check.mjs for everything)` : "";
console.log(failed ? `\n${failed} of ${selected.length} checks failed${note}.` : `\nAll ${selected.length} checks passed${note}.`);
process.exit(failed ? 1 : 0);
