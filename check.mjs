// One command to run every check in the repository: node check.mjs
//
// Runs the Python lint, format, import-rule and test checks, a check that the API contract and the
// TypeScript types generated from it are current, the TypeScript type-check and tests, the Node
// script tests, a check that setup.mjs's Windows path limit still fits the installed packages, a
// budget for the instruction files, and a check of what the documentation claims, then prints one
// line per check. Exits 1 if any fails, after printing the end of that check's output. CI runs
// this same command.
//
// node check.mjs --list prints the checks' names and runs nothing.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const WINDOWS = process.platform === "win32";
const BIN = join(ROOT, "python", ".venv", WINDOWS ? "Scripts" : "bin");
const tool = (name) => join(BIN, WINDOWS ? `${name}.exe` : name);

const python = join(ROOT, "python");
const CHECKS = [
  ["Python lint (ruff check)", tool("ruff"), ["check", "."], { cwd: python }],
  ["Python format (ruff format --check)", tool("ruff"), ["format", "--check", "."], { cwd: python }],
  ["Import rules (lint-imports)", tool("lint-imports"), [], { cwd: python }],
  // The contract is generated from the Python code, and the TypeScript types from the contract.
  // These two run before the type-check, so drift is reported as drift before it shows up as type errors.
  ["API contract (python -m helpdesk.contract)", tool("python"), ["-m", "helpdesk.contract", "check", "../contracts/openapi.json"], { cwd: python }],
  ["Python tests (pytest)", tool("python"), ["-m", "pytest", "-q", "-p", "no:cacheprovider"], { cwd: python }],
  // npm is a .cmd script on Windows, which Node only runs through a shell. The commands are fixed text.
  ["TypeScript API types (npm run api-types)", "npm run api-types -- --check", [], { cwd: join(ROOT, "ts"), shell: true }],
  ["TypeScript type-check", "npm run typecheck", [], { cwd: join(ROOT, "ts"), shell: true }],
  ["TypeScript tests", "npm test", [], { cwd: join(ROOT, "ts"), shell: true }],
  [
    "Script tests",
    process.execPath,
    ["--test", "postings/tally.test.mjs", "tools/harness-inventory.test.mjs", "tools/install-paths.test.mjs", "tools/instruction-files.test.mjs", "tools/doc-claims.test.mjs", "tools/git-run.test.mjs"],
    { cwd: ROOT },
  ],
  ["Setup's path limit (tools/install-paths.mjs)", process.execPath, ["tools/install-paths.mjs"], { cwd: ROOT }],
  // The lab's own budget for what its instruction files load: 200 lines, Claude Code's documented
  // target, and 4,000 estimated tokens, so long lines can't hide inside the line count.
  ["Instruction files (tools/instruction-files.mjs)", process.execPath, ["tools/instruction-files.mjs", ".", "--max-tokens", "4000"], { cwd: ROOT }],
  ["Documentation claims (tools/doc-claims.mjs)", process.execPath, ["tools/doc-claims.mjs", "."], { cwd: ROOT }],
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

let failed = 0;
for (const [label, command, args, options] of CHECKS) {
  const started = Date.now();
  const run = spawnSync(command, args, { encoding: "utf8", ...options });
  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  const ok = run.status === 0;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label} (${seconds}s)`);
  if (!ok) {
    failed++;
    const output = `${run.stdout ?? ""}${run.stderr ?? ""}${run.error ? run.error.message : ""}`.trimEnd();
    console.log(output.split("\n").slice(-25).map((line) => `      ${line}`).join("\n"));
  }
}
console.log(failed ? `\n${failed} of ${CHECKS.length} checks failed.` : `\nAll ${CHECKS.length} checks passed.`);
process.exit(failed ? 1 : 0);
