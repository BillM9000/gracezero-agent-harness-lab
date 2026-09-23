// Tests for tools/rework.mjs (chapter 31). Each test builds a small git repository whose commits
// have set dates, authors and co-author trailers, then checks what the rework count reports.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { isFix, main } from "./rework.mjs";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "rework.mjs");
const made = [];
after(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

const DAY = 24 * 60 * 60 * 1000;
const START = Date.parse("2026-01-01T12:00:00Z");
const AGENT_TRAILER = "\n\nCo-Authored-By: Claude <noreply@anthropic.com>";

// commits: [{ day, subject, files: { path: content }, agent: "trailer" | "author" | undefined }]
function repository(commits) {
  const root = mkdtempSync(join(tmpdir(), "rework-"));
  made.push(root);
  spawnSync("git", ["init", "-q"], { cwd: root });
  for (const c of commits) {
    for (const [path, content] of Object.entries(c.files)) {
      mkdirSync(dirname(join(root, path)), { recursive: true });
      writeFileSync(join(root, path), content);
    }
    const date = new Date(START + c.day * DAY).toISOString();
    const name = c.agent === "author" ? "Copilot" : "A Person";
    const message = c.subject + (c.agent === "trailer" ? AGENT_TRAILER : "");
    spawnSync("git", ["add", "-A"], { cwd: root });
    const commit = spawnSync("git", ["-c", `user.name=${name}`, "-c", "user.email=someone@example.com", "commit", "-q", "-m", message], {
      cwd: root,
      env: { ...process.env, GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date },
    });
    assert.equal(commit.status, 0, String(commit.stderr));
  }
  return root;
}

const row = (output, area) => output.split("\n").find((line) => line.trimStart().startsWith(`${area} `));

test("counts agent commits by a co-author trailer or by the author's name", () => {
  const root = repository([
    { day: 1, subject: "feat: a person's change", files: { "src/a.js": "1" } },
    { day: 2, subject: "feat: an agent's change", files: { "src/b.js": "1" }, agent: "trailer" },
    { day: 3, subject: "feat: another agent's change", files: { "src/c.js": "1" }, agent: "author" },
  ]);
  assert.match(main([root]), /^rework: 3 commits in the 90 days up to the latest; 2 \(67%\) name an agent as author or co-author\./);
});

test("a fix to a file an agent changed days before is rework, counted in that file's folder", () => {
  const root = repository([
    { day: 1, subject: "feat: add the form", files: { "client/src/form.js": "v1" }, agent: "trailer" },
    { day: 3, subject: "fix: the form drops the last field", files: { "client/src/form.js": "v2" } },
  ]);
  const output = main([root]);
  assert.match(output, /2 commits .* 1 \(50%\) name an agent/);
  assert.match(output, /1 are fixes; 1 of them change a file an agent commit had changed in the 14 days before\./);
  assert.match(row(output, "client/src"), /client\/src\s+1\s+1\s+100%\s+48\.0 h$/);
  assert.match(output, /Files counted most often[^\n]*\n\s+1\s+client\/src\/form\.js/);
});

test("a fix to a person's change, or to an agent change older than --within, is not rework", () => {
  const root = repository([
    { day: 1, subject: "feat: a person writes the parser", files: { "src/parse.js": "v1" } },
    { day: 1, subject: "feat: an agent writes the printer", files: { "src/print.js": "v1" }, agent: "trailer" },
    { day: 2, subject: "fix: the parser", files: { "src/parse.js": "v2" } },
    { day: 30, subject: "fix: the printer, a month later", files: { "src/print.js": "v2" } },
  ]);
  const output = main([root]);
  assert.match(output, /2 are fixes; 0 of them change a file an agent commit had changed/);
  assert.match(output, /No fix reworked recent agent work\./);
  assert.match(main([root, "--within", "30"]), /2 are fixes; 1 of them change a file/);
});

test("an agent change just before the window still counts for a fix inside it", () => {
  const root = repository([
    { day: 0, subject: "feat: the agent's change", files: { "src/a.js": "v1" }, agent: "trailer" },
    { day: 5, subject: "fix: correct it", files: { "src/a.js": "v2" } },
  ]);
  const output = main([root, "--days", "3"]);
  assert.match(output, /^rework: 1 commits in the 3 days up to the latest; 0 \(0%\)/);
  assert.match(output, /1 are fixes; 1 of them change a file an agent commit had changed/);
});

test("Markdown files don't make a fix rework, unless --all-files counts them", () => {
  const root = repository([
    { day: 1, subject: "feat: the agent's change", files: { "src/a.js": "v1", "CHANGELOG.md": "one" }, agent: "trailer" },
    { day: 2, subject: "fix: a person's own file, with a changelog line", files: { "src/b.js": "v1", "CHANGELOG.md": "two" } },
  ]);
  const output = main([root]);
  assert.match(output, /1 are fixes; 0 of them change a file/);
  assert.match(output, /Left out: Markdown files\./);
  assert.match(main([root, "--all-files"]), /1 are fixes; 1 of them change a file/);
});

test("--ignore leaves out files that change with every release", () => {
  const root = repository([
    { day: 1, subject: "feat: the agent's release", files: { "package.json": '{"version":"1.0.0"}', "src/a.js": "v1" }, agent: "trailer" },
    { day: 2, subject: "fix: a person's fix, with the version bumped", files: { "package.json": '{"version":"1.0.1"}', "src/b.js": "v1" } },
  ]);
  assert.match(main([root]), /1 are fixes; 1 of them change a file/);
  const output = main([root, "--ignore", "(^|/)package\\.json$"]);
  assert.match(output, /1 are fixes; 0 of them change a file/);
  assert.match(output, /Left out: Markdown files and files matching \/\(\^\|\\\/\)package\\\.json\$\/\./);
});

test("folders are grouped to --depth levels, and a fix counts once per folder", () => {
  const root = repository([
    { day: 1, subject: "feat: agent", files: { "server/routes/a.js": "v1", "server/routes/b.js": "v1", "top.js": "v1" }, agent: "trailer" },
    { day: 2, subject: "fix: both routes and the top file", files: { "server/routes/a.js": "v2", "server/routes/b.js": "v2", "top.js": "v2" } },
  ]);
  const deep = main([root]);
  assert.match(row(deep, "server/routes"), /server\/routes\s+1\s+1\s+100%/);
  assert.match(row(deep, "(root)"), /\(root\)\s+1\s+1\s+100%/);
  const shallow = main([root, "--depth", "1"]);
  assert.match(row(shallow, "server"), /server\s+1\s+1\s+100%/);
  assert.match(shallow, /\(by folder, 1 level\):/);
  assert.match(deep, /\(by folder, 2 levels\):/);
});

test("fix subjects: fix, fixes, fixed, fix(scope), hotfix and reverts count; fixture and prefix don't", () => {
  for (const subject of ["fix: x", "Fix the thing", "fix(ui): y", "Fixed z", "Fixes #3", "hotfix: a", 'Revert "b"', "revert: c"]) {
    assert.ok(isFix({ subject }), subject);
  }
  for (const subject of ["fixture: d", "prefix e", "feat: fix later", "refactor: f"]) {
    assert.ok(!isFix({ subject }), subject);
  }
});

// Chapter 31's Try it runs the count three times on this demo history; these are its numbers.
test("the demo history: bookkeeping files skew the count until they're left out", () => {
  const parent = mkdtempSync(join(tmpdir(), "rework-demo-"));
  made.push(parent);
  const demo = join(parent, "demo");
  const built = spawnSync(process.execPath, [join(dirname(SCRIPT), "rework-demo.mjs"), demo], { encoding: "utf8" });
  assert.equal(built.status, 0, built.stderr);
  const all = main([demo, "--all-files"]);
  assert.match(all, /12 commits .*; 6 \(50%\) name an agent/);
  assert.match(all, /5 are fixes; 5 of them change a file/);
  assert.match(row(all, "(root)"), /\(root\)\s+6\s+4\s+67%/);
  assert.match(all, /counted most often[^\n]*\n\s+3\s+CHANGELOG\.md\n\s+2\s+package\.json/);
  assert.match(row(main([demo]), "(root)"), /\(root\)\s+2\s+2\s+100%/);
  const clean = main([demo, "--ignore", "package\\.json$"]);
  assert.match(clean, /5 are fixes; 4 of them change a file/);
  assert.equal(row(clean, "(root)"), undefined);
  assert.match(row(clean, "client/src"), /client\/src\s+4\s+3\s+75%\s+1\.5 h$/);
  assert.match(row(clean, "server/db"), /server\/db\s+1\s+1\s+100%\s+120\.0 h$/);
});

test("refuses a folder that isn't a repository, and a bad number", () => {
  const empty = mkdtempSync(join(tmpdir(), "rework-empty-"));
  made.push(empty);
  const notRepo = spawnSync(process.execPath, [SCRIPT, empty], { encoding: "utf8" });
  assert.equal(notRepo.status, 2);
  assert.match(notRepo.stderr, /isn't a git repository with commits/);
  const badDays = spawnSync(process.execPath, [SCRIPT, empty, "--days", "0"], { encoding: "utf8" });
  assert.equal(badDays.status, 2);
  assert.match(badDays.stderr, /--days needs a whole number of 1 or more/);
});
