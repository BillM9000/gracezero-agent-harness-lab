// Proves the instruction-file check measures what loads, follows imports the way Claude Code's
// documentation describes, and fails on each problem it claims to catch.
// Run: node --test tools/instruction-files.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "instruction-files.mjs");
const base = mkdtempSync(join(tmpdir(), "instruction-files-"));
after(() => rmSync(base, { recursive: true, force: true }));

let n = 0;
function repo(files) {
  const root = join(base, `repo-${++n}`);
  mkdirSync(root, { recursive: true });
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  return root;
}

function check(root, ...args) {
  const run = spawnSync(process.execPath, [SCRIPT, root, ...args], { encoding: "utf8", timeout: 20000 });
  return { status: run.status, output: `${run.stdout}${run.stderr}` };
}

const linesOf = (count) => Array.from({ length: count }, (_, i) => `Rule ${i + 1}.`).join("\n") + "\n";

test("a small file passes and reports its lines, words and estimated tokens", () => {
  const { status, output } = check(repo({ "AGENTS.md": "# Rules\r\n\r\nOne.\r\n" }));
  assert.equal(status, 0, output);
  // 3 lines, 3 words, 14 characters once Windows line endings count as one: 14 / 2.5 rounds to 6.
  assert.match(output, /AGENTS\.md\s+session start\s+3\s+3\s+6/);
  assert.match(output, /No problems found\./);
});

test("a file over the line budget fails, naming the file and the budget", () => {
  const { status, output } = check(repo({ "AGENTS.md": linesOf(201) }));
  assert.equal(status, 1);
  assert.match(output, /AGENTS\.md loads 201 lines, over the budget of 200\./);
});

test("a few very long lines pass the line budget but fail a token budget", () => {
  const root = repo({ "AGENTS.md": `${"word ".repeat(1000)}\n`.repeat(3) });
  assert.equal(check(root).status, 0);
  const { status, output } = check(root, "--max-tokens", "4000");
  assert.equal(status, 1);
  assert.match(output, /AGENTS\.md loads about 6,001 tokens, over the budget of 4,000\./);
});

test("an import loads with the file that names it, and each file counts once", () => {
  const root = repo({ "CLAUDE.md": "@AGENTS.md\n@AGENTS.md\n", "AGENTS.md": `@CLAUDE.md\n${linesOf(9)}` });
  const { status, output } = check(root);
  assert.equal(status, 0, output);
  assert.match(output, /CLAUDE\.md\s+session start\s+12\s.*AGENTS\.md/);
});

test("text in a code span or a fenced code block is not an import", () => {
  const root = repo({
    "CLAUDE.md": "Mention `@missing.md` as text.\n\n```\n@also-missing.md\n```\n\n@AGENTS.md\n",
    "AGENTS.md": "# Rules\n",
  });
  const { status, output } = check(root);
  assert.equal(status, 0, output);
});

test("an import that isn't a file fails", () => {
  const { status, output } = check(repo({ "CLAUDE.md": "@docs/missing.md\n" }));
  assert.equal(status, 1);
  assert.match(output, /CLAUDE\.md imports @docs\/missing\.md, which isn't a file in this repository/);
});

test("an import five hops deep never loads", () => {
  const root = repo({
    "CLAUDE.md": "@a.md\n",
    "a.md": "@b.md\n",
    "b.md": "@c.md\n",
    "c.md": "@d.md\n",
    "d.md": "@e.md\n",
    "e.md": "Too deep.\n",
  });
  const { status, output } = check(root);
  assert.equal(status, 1);
  assert.match(output, /d\.md imports @e\.md, 5 hops from CLAUDE\.md\. Claude Code follows imports only 4 hops deep/);
});

test("a CLAUDE.md beside an AGENTS.md fails unless it imports it", () => {
  const { status, output } = check(repo({ "CLAUDE.md": "Read AGENTS.md.\n", "AGENTS.md": "# Rules\n", "pkg/CLAUDE.md": "Nothing.\n", "pkg/AGENTS.md": "# More\n" }));
  assert.equal(status, 1);
  assert.match(output, /- CLAUDE\.md sits beside AGENTS\.md but doesn't import it/);
  assert.match(output, /- pkg\/CLAUDE\.md sits beside pkg\/AGENTS\.md but doesn't import it/);
  assert.match(output, /Add a line that reads @AGENTS\.md to CLAUDE\.md\./);
});

test("files in subfolders load on demand", () => {
  const { output } = check(repo({ "AGENTS.md": "# Rules\n", "pkg/AGENTS.md": "# More\n", ".github/copilot-instructions.md": "Be brief.\n" }));
  assert.match(output, /^AGENTS\.md\s+session start/m);
  assert.match(output, /^\.github\/copilot-instructions\.md\s+session start/m);
  assert.match(output, /^pkg\/AGENTS\.md\s+on demand/m);
});

test("an import from outside the repository is left alone", () => {
  const { status, output } = check(repo({ "CLAUDE.md": "@~/.claude/my-notes.md\n@../shared/rules.md\n" }));
  assert.equal(status, 0, output);
});

test("a budget that isn't a whole number is refused", () => {
  const { status, output } = check(repo({ "AGENTS.md": "# Rules\n" }), "--max-tokens", "0");
  assert.equal(status, 2);
  assert.match(output, /--max-tokens needs a whole number greater than 0\./);
});
