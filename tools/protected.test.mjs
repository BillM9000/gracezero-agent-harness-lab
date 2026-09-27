// Tests for tools/protected.mjs (chapters 25 and 34): the fix loop's protected list covers every
// check node check.mjs runs, and a tool's configuration file wherever it appears.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { CHECK_FILES, CONFIG_NAMES, isProtected } from "./protected.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const tracked = spawnSync("git", ["ls-files", "-z"], { cwd: ROOT, encoding: "utf8" }).stdout.split("\0").filter(Boolean);

test("every check node check.mjs runs has its files listed, and nothing else is listed", () => {
  const listed = spawnSync(process.execPath, ["check.mjs", "--list"], { cwd: ROOT, encoding: "utf8" });
  const labels = listed.stdout.trim().split(/\r?\n/);
  assert.ok(labels.length > 15, listed.stdout);
  const missing = labels.filter((label) => !(label in CHECK_FILES));
  assert.deepEqual(missing, [], "add each new check to CHECK_FILES in tools/protected.mjs");
  assert.deepEqual(Object.keys(CHECK_FILES).filter((label) => !labels.includes(label)), []);
});

test("every pattern a check lists matches a file in the repository", () => {
  for (const [label, patterns] of Object.entries(CHECK_FILES)) {
    for (const pattern of patterns) assert.ok(tracked.some((file) => pattern.test(file)), `${label}: ${pattern} matches nothing`);
  }
});

// The module each `python -m NAME` runs, as a file: NAME.py, or the package's folder.
function moduleFile(name) {
  const base = join("python", "src", ...name.split("."));
  if (existsSync(join(ROOT, `${base}.py`))) return `${base}.py`.replaceAll("\\", "/");
  if (existsSync(join(ROOT, base, "__main__.py"))) return `${base}/__main__.py`.replaceAll("\\", "/");
  assert.equal(name, "pytest", `python -m ${name}: no module in python/src`);
  return null; // not the lab's
}

test("what check.mjs runs is protected: each Python module, each script and the npm scripts' file", () => {
  const source = readFileSync(join(ROOT, "check.mjs"), "utf8");
  const run = [];
  for (const m of source.matchAll(/"-m", "([\w.]+)"/g)) {
    const file = moduleFile(m[1]);
    if (file) run.push(file);
  }
  for (const m of source.matchAll(/"((?:tools|postings)\/[\w./-]+\.mjs)"/g)) run.push(m[1]);
  if (/npm run /.test(source)) run.push("ts/package.json");
  assert.ok(run.includes("python/src/helpdesk/contract.py") && run.includes("tools/progress.mjs"), run.join("\n"));
  assert.deepEqual(run.filter((file) => !isProtected(file)), []);
  assert.ok(isProtected("check.mjs"));
});

test("the checks' data and records are protected, the app's own files aren't", () => {
  for (const file of [
    "python/catalog/servers.toml",
    "python/agents/models.toml",
    "python/src/mcp_governance/catalog.py",
    "python/requirements-lock.txt",
    "postings/tally.test.mjs",
  ]) {
    assert.ok(isProtected(file), file);
  }
  for (const file of [
    "python/src/helpdesk/services/tickets.py",
    "python/agents/triage.toml",
    "README.md",
    "progress/features.json",
    "ts/src/client.ts",
  ]) {
    assert.ok(!isProtected(file), file);
  }
});

test("a tool's configuration file is protected in any folder, new or not", () => {
  for (const file of [
    "python/ruff.toml",
    "ruff.toml",
    "python/src/.ruff.toml",
    "python/src/helpdesk/pyproject.toml",
    "python/setup.cfg",
    "tox.ini",
    "python/pytest.ini",
    "python/src/conftest.py",
    "python/.importlinter",
    "python/.flake8",
    "package.json",
    "ts/tsconfig.build.json",
    "ts/src/tsconfig.json",
    "ts/eslint.config.mjs",
    "ts/.eslintrc.json",
    "ts/.dependency-cruiser.json",
    "ts/vitest.config.ts",
    "python/.gitignore",
    ".gitattributes",
  ]) {
    assert.ok(isProtected(file), file);
  }
  for (const file of ["python/src/helpdesk/config.py", "ts/src/package.ts", "docs/ruff.toml.md", "python/tox.ini.bak"]) {
    assert.ok(!CONFIG_NAMES.test(file), file);
  }
});
