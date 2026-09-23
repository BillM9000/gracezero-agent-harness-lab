// Proves the documentation-claims check fails on each kind of drift it claims to catch, and leaves
// alone what it says it doesn't check.
// Run: node --test tools/doc-claims.test.mjs
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "doc-claims.mjs");
const base = mkdtempSync(join(tmpdir(), "doc-claims-"));
after(() => rmSync(base, { recursive: true, force: true }));

// A small repository with something for every counter to count, plus the files given.
const BASE_FILES = {
  "tools/a.mjs": "",
  "python/pyproject.toml": "[[tool.importlinter.contracts]]\n[[tool.importlinter.contracts]]\n",
  "postings/sample-2026-09-22.json": JSON.stringify({ postings: [{}, {}, {}] }),
  "check.mjs": 'if (process.argv.includes("--list")) console.log("First check\\nSecond check");\n',
};

let n = 0;
function repo(files) {
  const root = join(base, `repo-${++n}`);
  for (const [path, content] of Object.entries({ ...BASE_FILES, ...files })) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  return root;
}

function check(root) {
  const run = spawnSync(process.execPath, [SCRIPT, root], { encoding: "utf8" });
  return { status: run.status, output: `${run.stdout}${run.stderr}` };
}

test("paths that exist and numbers that match pass, and the report shows each number", () => {
  const { status, output } = check(repo({ "README.md": "See `tools/a.mjs`.\n\nThere are <!-- claim: import-contracts -->2 rules.\n" }));
  assert.equal(status, 0, output);
  assert.match(output, /README\.md:3\s+import-contracts\s+says 2, counted 2/);
  assert.match(output, /Only paths and marked numbers are checked; the rest of the prose isn't\./);
});

test("a path that no longer exists fails, naming the line", () => {
  const { status, output } = check(repo({ "README.md": "# Readme\n\nRun `tools/gone.mjs`.\n" }));
  assert.equal(status, 1);
  assert.match(output, /README\.md:3: `tools\/gone\.mjs` doesn't exist\. Fix the path in the document, or restore the file\./);
});

test("folders, placeholders, commands and setup's folders aren't taken for missing files", () => {
  const readme = "`tools/` `tools/<name>.mjs` `node tools/x.mjs` `python/.venv/Scripts/python.exe` `ts/node_modules/`\n";
  const { status, output } = check(repo({ "README.md": readme }));
  assert.equal(status, 0, output);
});

test("a number that has drifted fails, giving both numbers and the fix", () => {
  const { status, output } = check(repo({ "README.md": "We coded <!-- claim: postings -->5 postings.\n" }));
  assert.equal(status, 1);
  assert.match(output, /README\.md:1: says 5 postings in the chapter 1 sample, but there are 3\. Update the document, or the code if the document is right\./);
});

test("a marker must name a known counter and be followed by its number", () => {
  const { status, output } = check(repo({ "README.md": "<!-- claim: widgets -->4\n<!-- claim: postings --> about thirty\n" }));
  assert.equal(status, 1);
  assert.match(output, /README\.md:1: <!-- claim: widgets --> names no counter\. Known counters: checks, import-contracts, postings\./);
  assert.match(output, /README\.md:2: <!-- claim: postings --> must be followed straight away by the number it claims\./);
});

test("the checks counter asks check.mjs for its list", () => {
  assert.equal(check(repo({ "AGENTS.md": "All <!-- claim: checks -->2 checks.\n" })).status, 0);
  const { status, output } = check(repo({ "AGENTS.md": "All <!-- claim: checks -->3 checks.\n" }));
  assert.equal(status, 1);
  assert.match(output, /says 3 checks that node check\.mjs runs, but there are 2/);
});

test("a relative link that leads nowhere fails, and a web address is left alone", () => {
  const { status, output } = check(repo({ "README.md": "[the guide](docs/guide.md) and [the site](https://example.com/x)\n" }));
  assert.equal(status, 1);
  assert.match(output, /README\.md:1: the link to docs\/guide\.md leads nowhere/);
  assert.doesNotMatch(output, /example\.com/);
});

test("a marker written in backticks is an example of the syntax, not a claim", () => {
  const { status, output } = check(repo({ "AGENTS.md": "Mark numbers with `<!-- claim: NAME -->`.\n" }));
  assert.equal(status, 0, output);
});

test("a file on disk that git doesn't track is reported as untracked, not as present", () => {
  const root = repo({ "README.md": "Run `tools/a.mjs`, then `tools/new.mjs`.\n" });
  const git = (...args) => execFileSync("git", ["-C", root, ...args], { encoding: "utf8" });
  git("init", "-q");
  git("add", "README.md", "tools/a.mjs");
  git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "fixture");
  writeFileSync(join(root, "tools", "new.mjs"), "");
  const { status, output } = check(root);
  assert.equal(status, 1);
  assert.match(output, /README\.md:1: `tools\/new\.mjs` is on disk but not tracked by git, so no one else has it\./);
  assert.doesNotMatch(output, /tools\/a\.mjs/);
});

test("the changelog and code blocks are history and examples, so they aren't checked", () => {
  const files = { "CHANGELOG.md": "Removed `tools/old.mjs`.\n", "README.md": "```\nnode tools/missing.mjs\n`tools/missing.mjs`\n```\n" };
  const { status, output } = check(repo(files));
  assert.equal(status, 0, output);
});
