// Lists the evidence a repository's files give for each of the eight parts of a harness
// (chapter 4). It reports what it finds and where; it doesn't score. "None found" means no
// evidence in the files, not that the part doesn't exist: some parts, such as required
// reviews and measurement, usually live outside the repository.
//
// Usage: node tools/harness-inventory.mjs [path]   (default: the current folder)
//
// The file names come from each tool's own documentation, read on 2026-09-22:
//   AGENTS.md anywhere in the tree (agents.md); CLAUDE.md and GEMINI.md (GitHub Copilot's
//   instructions docs also accept them); .github/copilot-instructions.md and
//   .github/instructions/*.instructions.md (GitHub Copilot); .claude/settings.json with
//   "permissions" and "hooks" keys (Claude Code settings); .mcp.json at the root (Claude Code
//   MCP); CODEOWNERS in .github/, the root or docs/, and pull request templates (GitHub).
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const SKIP = new Set([".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"]);

// Tracked files when the folder is in a git repository, so ignored and generated files don't
// count; otherwise every file below the folder, skipping dependency and build folders.
export function listFiles(root) {
  try {
    const out = execFileSync("git", ["-C", root, "ls-files"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    const tracked = out.split("\n").filter(Boolean);
    if (tracked.length) return tracked;
  } catch {
    // Not a git repository: fall through to walking the folder.
  }
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (SKIP.has(entry.name)) continue;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else files.push(relative(root, path).split(sep).join("/"));
    }
  };
  walk(root);
  return files;
}

function gitConfig(root, key) {
  try {
    return execFileSync("git", ["-C", root, "config", "--get", key], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return "";
  }
}

export function inventory(root) {
  const files = listFiles(root);
  const text = (f) => readFileSync(join(root, f), "utf8");
  const lineCount = (f) => text(f).split(/\r?\n/).filter((line, i, all) => i < all.length - 1 || line !== "").length;
  const matching = (re) => files.filter((f) => re.test(f));
  const json = (f) => {
    try {
      return JSON.parse(text(f));
    } catch {
      return null;
    }
  };
  const settings = files.includes(".claude/settings.json") ? json(".claude/settings.json") : null;
  const workflows = matching(/^\.github\/workflows\/[^/]+\.ya?ml$/);
  // Every pyproject.toml, not only the root one: many repositories keep Python in a subfolder.
  const pyproject = matching(/(^|\/)pyproject\.toml$/).map(text).join("\n");
  const found = {};

  found.context = [
    ...matching(/(^|\/)(AGENTS|CLAUDE|GEMINI)\.md$/),
    ...matching(/^\.github\/copilot-instructions\.md$/),
    ...matching(/^\.github\/instructions\/.+\.instructions\.md$/),
  ].map((f) => `${f} (${plural(lineCount(f), "line")})`);

  found.tools = matching(/^\.mcp\.json$/).map((f) => `${f} (MCP servers)`);

  const rules = settings?.permissions;
  found.permissions = rules
    ? [`.claude/settings.json (${(rules.allow ?? []).length} allow, ${(rules.deny ?? []).length} deny rules)`]
    : [];

  const tests = matching(/(^|\/)(tests?|__tests__)\/|\.(test|spec)\.[cm]?[jt]sx?$|(^|\/)test_[^/]+\.py$|_test\.(py|go)$/);
  const checks = [];
  if (workflows.length) checks.push(`CI: ${plural(workflows.length, "workflow file")}`);
  if (tests.length) checks.push(plural(tests.length, "test file"));
  if (/^\[tool\.ruff/m.test(pyproject)) checks.push("ruff");
  if (/^\[tool\.mypy\]/m.test(pyproject) || matching(/(^|\/)mypy\.ini$/).length) checks.push("mypy");
  const contracts = (pyproject.match(/^\[\[tool\.importlinter\.contracts\]\]/gm) ?? []).length;
  if (contracts) checks.push(`import-linter (${plural(contracts, "contract")})`);
  const eslint = matching(/(^|\/)(eslint\.config\.[cm]?[jt]s|\.eslintrc(\.[a-z]+)?)$/);
  if (eslint.length) checks.push(`ESLint (${plural(eslint.length, "config file")})`);
  if (eslint.some((f) => text(f).includes("no-restricted-imports"))) checks.push("ESLint import rules");
  if (matching(/(^|\/)\.dependency-cruiser\.[cm]?js(on)?$/).length) checks.push("dependency-cruiser");
  const tsconfigs = matching(/(^|\/)tsconfig[^/]*\.json$/);
  if (tsconfigs.length) checks.push(`TypeScript (${plural(tsconfigs.length, "tsconfig file")})`);
  found.checks = checks;

  const feedback = [];
  const hooks = settings?.hooks && Object.keys(settings.hooks).length ? Object.keys(settings.hooks) : [];
  if (hooks.length) feedback.push(`agent hooks in .claude/settings.json: ${hooks.join(", ")}`);
  const hooksPath = gitConfig(root, "core.hooksPath");
  if (hooksPath) feedback.push(`git hooks path: ${hooksPath}`);
  if (matching(/^\.husky\//).length) feedback.push("husky git hooks");
  if (files.includes(".pre-commit-config.yaml")) feedback.push("pre-commit hooks");
  if (workflows.some((f) => /pull_request/.test(text(f)))) feedback.push("CI runs on pull requests");
  found.feedback = feedback;

  found.state = [
    ...matching(/(^|\/)CHANGELOG\.md$/i),
    ...matching(/(^|\/)[^/]*(handoff|progress)[^/]*\.(md|txt|json)$/i),
  ];

  found.review = [
    ...matching(/^(\.github\/|docs\/)?CODEOWNERS$/),
    ...matching(/^(\.github\/|docs\/)?pull_request_template\.md$/i),
    ...matching(/^\.github\/PULL_REQUEST_TEMPLATE\//i),
  ];

  return found;
}

const PARTS = [
  ["context", "1. Context"],
  ["tools", "2. Tools"],
  ["permissions", "3. Permissions"],
  ["checks", "4. Checks"],
  ["feedback", "5. Feedback loops"],
  ["state", "6. Session state"],
  ["review", "7. Review"],
];

export function report(root) {
  const found = inventory(root);
  const lines = [`Harness inventory: ${root}`, ""];
  for (const [key, label] of PARTS) {
    lines.push(`${label.padEnd(18)} ${found[key].length ? found[key].join("; ") : "none found"}`);
  }
  lines.push(`${"8. Measurement".padEnd(18)} can't be seen in files: ask what is measured, and where (chapter 26)`);
  lines.push("", '"none found" means no evidence in the files. Check the hosting service and CI settings too.');
  return lines.join("\n");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  console.log(report(process.argv[2] ?? "."));
}
