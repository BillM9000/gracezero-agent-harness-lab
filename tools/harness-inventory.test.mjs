// Proves the inventory finds each kind of evidence, ignores dependency folders and untracked
// files, and says "none found" instead of guessing.
// Run: node --test tools/harness-inventory.test.mjs
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";

import { inventory, report } from "./harness-inventory.mjs";

const base = mkdtempSync(join(tmpdir(), "inventory-"));
after(() => rmSync(base, { recursive: true, force: true }));

let n = 0;
function repo(files) {
  const root = join(base, `repo-${++n}`);
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  mkdirSync(root, { recursive: true });
  return root;
}

const FULL = {
  "AGENTS.md": "# Rules\n\nOne.\nTwo.\n",
  "CLAUDE.md": "Read AGENTS.md.\n",
  ".github/copilot-instructions.md": "Be brief.\n",
  ".mcp.json": "{}",
  ".claude/settings.json": JSON.stringify({ permissions: { allow: ["a", "b"], deny: ["c"] }, hooks: { PostToolUse: [] } }),
  ".github/workflows/ci.yml": "on:\n  pull_request:\n",
  "tests/test_app.py": "",
  "src/app.test.ts": "",
  "pyproject.toml": "[tool.ruff]\n[[tool.importlinter.contracts]]\n[[tool.importlinter.contracts]]\n",
  "eslint.config.js": "export default [{ rules: { 'no-restricted-imports': 'error' } }];",
  "CHANGELOG.md": "",
  "memory/session_handoff.md": "",
  ".github/CODEOWNERS": "* @team",
  ".github/pull_request_template.md": "",
  "node_modules/pkg/AGENTS.md": "not ours",
};

test("every kind of evidence is found and named", () => {
  const found = inventory(repo(FULL));
  assert.deepEqual(found.context, ["AGENTS.md (4 lines)", "CLAUDE.md (1 line)", ".github/copilot-instructions.md (1 line)"]);
  assert.deepEqual(found.tools, [".mcp.json (MCP servers)"]);
  assert.deepEqual(found.permissions, [".claude/settings.json (2 allow, 1 deny rules)"]);
  assert.deepEqual(found.checks, [
    "CI: 1 workflow file",
    "2 test files",
    "ruff",
    "import-linter (2 contracts)",
    "ESLint (1 config file)",
    "ESLint import rules",
  ]);
  assert.deepEqual(found.feedback, ["agent hooks in .claude/settings.json: PostToolUse", "CI runs on pull requests"]);
  assert.deepEqual(found.state, ["CHANGELOG.md", "memory/session_handoff.md"]);
  assert.deepEqual(found.review, [".github/CODEOWNERS", ".github/pull_request_template.md"]);
});

test("Python settings are found in a subfolder, not only at the root", () => {
  const found = inventory(repo({ "python/pyproject.toml": "[tool.ruff]\n[[tool.importlinter.contracts]]\n" }));
  assert.deepEqual(found.checks, ["ruff", "import-linter (1 contract)"]);
});

test("dependency folders are never counted", () => {
  const found = inventory(repo(FULL));
  assert.ok(!found.context.some((f) => f.includes("node_modules")));
});

test("an empty repository gets 'none found' for every part it can see, never a guess", () => {
  const text = report(repo({ "README.md": "hello\n" }));
  for (const label of ["1. Context", "2. Tools", "3. Permissions", "4. Checks", "5. Feedback loops", "6. Session state", "7. Review"]) {
    assert.match(text, new RegExp(`${label.replace(".", "\\.")}\\s+none found`));
  }
  assert.match(text, /8\. Measurement\s+can't be seen in files/);
});

test("in a git repository only tracked files count", () => {
  const root = repo({ "AGENTS.md": "tracked\n", "CLAUDE.md": "untracked\n" });
  const git = (...args) => execFileSync("git", ["-C", root, ...args], { stdio: "ignore" });
  git("init", "-q");
  git("add", "AGENTS.md");
  git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "one file");
  assert.deepEqual(inventory(root).context, ["AGENTS.md (1 line)"]);
});

test("a git hooks path set in the repository's config is reported", () => {
  const root = repo({ "AGENTS.md": "x\n" });
  const git = (...args) => execFileSync("git", ["-C", root, ...args], { stdio: "ignore" });
  git("init", "-q");
  git("config", "core.hooksPath", "bin/git-hooks");
  git("add", ".");
  git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "x");
  assert.deepEqual(inventory(root).feedback, ["git hooks path: bin/git-hooks"]);
});
