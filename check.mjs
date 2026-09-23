// One command to run every check in the repository: node check.mjs
//
// Runs the Python lint, format, import-rule and test checks, the TypeScript type-check and
// tests, the Node script tests, and a check that setup.mjs's Windows path limit still fits the
// installed packages, then prints one line per check. Exits 1 if any fails, after printing the
// end of that check's output. CI runs this same command.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const WINDOWS = process.platform === "win32";
const BIN = join(ROOT, "python", ".venv", WINDOWS ? "Scripts" : "bin");
const tool = (name) => join(BIN, WINDOWS ? `${name}.exe` : name);

const missing = [];
if (!existsSync(tool("python"))) missing.push("python/.venv");
if (!existsSync(join(ROOT, "ts", "node_modules"))) missing.push("ts/node_modules");
if (missing.length) {
  console.error(`Not set up yet (missing ${missing.join(" and ")}). Run node setup.mjs first.`);
  process.exit(1);
}

const python = join(ROOT, "python");
const CHECKS = [
  ["Python lint (ruff check)", tool("ruff"), ["check", "."], { cwd: python }],
  ["Python format (ruff format --check)", tool("ruff"), ["format", "--check", "."], { cwd: python }],
  ["Import rules (lint-imports)", tool("lint-imports"), [], { cwd: python }],
  ["Python tests (pytest)", tool("python"), ["-m", "pytest", "-q", "-p", "no:cacheprovider"], { cwd: python }],
  // npm is a .cmd script on Windows, which Node only runs through a shell. The commands are fixed text.
  ["TypeScript type-check", "npm run typecheck", [], { cwd: join(ROOT, "ts"), shell: true }],
  ["TypeScript tests", "npm test", [], { cwd: join(ROOT, "ts"), shell: true }],
  [
    "Script tests",
    process.execPath,
    ["--test", "postings/tally.test.mjs", "tools/harness-inventory.test.mjs", "tools/install-paths.test.mjs"],
    { cwd: ROOT },
  ],
  ["Setup's path limit (tools/install-paths.mjs)", process.execPath, ["tools/install-paths.mjs"], { cwd: ROOT }],
];

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
