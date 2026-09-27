// Tests for tools/fix-loop.mjs (chapter 25). Each test builds a small git repository whose
// check.mjs fails while app.txt says "bug", then runs the loop with a scripted fake agent: one
// that fixes it, one that never manages to, one that does nothing, one that edits the check.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { git as runGit } from "./git-run.mjs";

const LOOP = join(dirname(fileURLToPath(import.meta.url)), "fix-loop.mjs");
const made = [];
after(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

function temporary(prefix) {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  made.push(dir);
  return dir;
}

// Through tools/git-run.mjs: the machine's git setup stays out, and a failed call throws with
// everything git printed. Returns git's stdout.
function git(root, ...args) {
  return runGit(root, ["-c", "user.email=test@example.com", "-c", "user.name=test", ...args]);
}

// The check prints what app.txt says, so an attempt that changes it changes the report.
const CHECK = `import { readFileSync } from "node:fs";
const text = readFileSync("app.txt", "utf8").trim();
console.log("PASS  Stub lint (0.1s)");
if (text.includes("bug")) {
  console.log("FAIL  Stub check (0.2s)\\n      app.txt should say ok, and says: " + text + "\\n\\n1 of 2 checks failed.");
  process.exit(1);
}
console.log("\\nAll 2 checks passed.");
`;

function repository(app = "bug") {
  const root = temporary("fix-loop-");
  writeFileSync(join(root, "check.mjs"), CHECK);
  writeFileSync(join(root, "app.txt"), `${app}\n`);
  git(root, "init", "-q");
  git(root, "add", ".");
  git(root, "commit", "-q", "-m", "fixture");
  return root;
}

// Fake agents live outside the repository, count their calls, and keep the last prompt.
const AGENTS = {
  fixer: 'writeFileSync("app.txt", "ok\\n");',
  busy: 'writeFileSync("app.txt", readFileSync("app.txt", "utf8") + "bug " + calls + "\\n");',
  idle: "",
  cheater: 'writeFileSync("check.mjs", "console.log(\\"All checks passed.\\");\\n");',
};
function agent(kind) {
  const dir = temporary("fake-agent-");
  const script = join(dir, "agent.mjs");
  writeFileSync(
    script,
    `import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";\n` +
      `import { execSync } from "node:child_process";\n` +
      `const count = ${JSON.stringify(join(dir, "calls.txt"))};\n` +
      `const calls = (existsSync(count) ? Number(readFileSync(count, "utf8")) : 0) + 1;\n` +
      `writeFileSync(count, String(calls));\n` +
      `writeFileSync(${JSON.stringify(join(dir, "prompt.txt"))}, readFileSync(0, "utf8"));\n` +
      `${AGENTS[kind]}\n`,
  );
  const calls = () => (existsSync(join(dir, "calls.txt")) ? Number(readFileSync(join(dir, "calls.txt"), "utf8")) : 0);
  const prompt = () => readFileSync(join(dir, "prompt.txt"), "utf8");
  return { command: `node "${script}"`, calls, prompt };
}

function loop(root, ...args) {
  const run = spawnSync(process.execPath, [LOOP, ...args], { cwd: root, encoding: "utf8" });
  return { code: run.status, output: run.stdout + run.stderr };
}

test("checks that already pass never call the agent", () => {
  const fake = agent("fixer");
  const { code, output } = loop(repository("ok"), "--agent", fake.command);
  assert.equal(code, 0, output);
  assert.match(output, /already pass; nothing to do/);
  assert.equal(fake.calls(), 0);
});

test("an agent that fixes the failure ends the loop after one attempt", () => {
  const root = repository();
  const fake = agent("fixer");
  const { code, output } = loop(root, "--agent", fake.command);
  assert.equal(code, 0, output);
  assert.match(output, /the fast checks pass after 1 attempt\./);
  assert.match(output, /Left in the working tree for review:\n M app\.txt/);
  assert.equal(fake.calls(), 1);
});

test("the prompt carries the report, how to rerun the checks, the rules and the attempt", () => {
  const fake = agent("fixer");
  loop(repository(), "--agent", fake.command);
  const prompt = fake.prompt();
  assert.match(prompt, /^The fast checks in this repository fail\. Make them pass\./);
  assert.match(prompt, /FAIL {2}Stub check \(0\.2s\)\n {6}app\.txt should say ok, and says: bug/);
  assert.doesNotMatch(prompt, /PASS/);
  assert.match(prompt, /Run them with: node check\.mjs --fast/);
  assert.match(prompt, /Don't weaken or skip a test, a rule or a check to make it pass\./);
  assert.match(prompt, /This is attempt 1 of 3\.$/);
});

test("stops after three attempts when the agent keeps changing things without fixing them", () => {
  const fake = agent("busy");
  const { code, output } = loop(repository(), "--agent", fake.command);
  assert.equal(code, 1);
  assert.match(output, /still fail after 3 attempts/);
  assert.match(output, /What the checks still report:\nFAIL {2}Stub check/);
  assert.equal(fake.calls(), 3);
});

test("--attempts sets the cap", () => {
  const fake = agent("busy");
  const { code, output } = loop(repository(), "--agent", fake.command, "--attempts", "2");
  assert.equal(code, 1);
  assert.match(output, /still fail after 2 attempts/);
  assert.equal(fake.calls(), 2);
});

test("stops at once when an attempt leaves the checks reporting the same thing", () => {
  const fake = agent("idle");
  const { code, output } = loop(repository(), "--agent", fake.command);
  assert.equal(code, 1);
  assert.match(output, /no progress: after attempt 1 the checks report exactly what they did before/);
  assert.equal(fake.calls(), 1);
});

test("stops when the agent changes the checks, and leaves the change for a person", () => {
  const root = repository();
  const fake = agent("cheater");
  const { code, output } = loop(root, "--agent", fake.command);
  assert.equal(code, 1);
  assert.match(output, /the agent changed the checks themselves \(check\.mjs\), and with that change they pass\. Stopping: a person needs to review that\./);
  assert.doesNotMatch(output, /pass after/);
  assert.match(git(root, "status", "--short"), /M check\.mjs/);
});

test("an agent command that fails to run is reported, and not tried again", () => {
  const { code, output } = loop(repository(), "--agent", "node no-such-agent.mjs");
  assert.equal(code, 1);
  assert.match(output, /the agent exited 1 after/);
  assert.match(output, /Cannot find module/);
  assert.match(output, /no progress/);
});

test("refuses without an agent command, outside a repository root, or with a silly cap", () => {
  assert.equal(loop(repository()).code, 2);
  assert.equal(loop(repository(), "--agent", "node x.mjs", "--attempts", "0").code, 2);
  assert.equal(loop(temporary("not-a-repo-"), "--agent", "node x.mjs").code, 2);
});

// The holes a review found (2026-09-26): what the protected list didn't cover, and a commit, which
// takes an attempt's changes out of the working tree a person reviews.
const FIXED = 'writeFileSync("app.txt", "ok\\n");';

test("a new tool configuration file stops the loop, in any folder: python/ruff.toml", () => {
  AGENTS.configurer = `${FIXED} mkdirSync("python", { recursive: true }); writeFileSync("python/ruff.toml", "[lint]\\nignore = [\\"F401\\"]\\n");`;
  const { code, output } = loop(repository(), "--agent", agent("configurer").command);
  assert.equal(code, 1, output);
  assert.match(output, /the agent changed the checks themselves \(python\/ruff\.toml\), and with that change they pass\./);
});

test("the checks' records and data stop the loop: the gate's promotion record", () => {
  const root = repository();
  mkdirSync(join(root, "python", "evals"), { recursive: true });
  writeFileSync(join(root, "python", "evals", "promoted.json"), '{"promoted": "2026-09-25"}\n');
  git(root, "add", ".");
  git(root, "commit", "-q", "-m", "more fixture");
  AGENTS.promoter = `${FIXED} writeFileSync("python/evals/promoted.json", '{"promoted": "2026-09-27"}\\n');`;
  const { code, output } = loop(root, "--agent", agent("promoter").command);
  assert.equal(code, 1, output);
  assert.match(output, /the agent changed the checks themselves \(python\/evals\/promoted\.json\)/);
});

test("hiding a new configuration file from git stops the loop: .gitignore and info/exclude", () => {
  AGENTS.ignorer = `${FIXED} writeFileSync(".gitignore", "ruff.toml\\n"); writeFileSync("ruff.toml", "[lint]\\nignore = [\\"F401\\"]\\n");`;
  const ignored = loop(repository(), "--agent", agent("ignorer").command);
  assert.equal(ignored.code, 1, ignored.output);
  assert.match(ignored.output, /the agent changed the checks themselves \(\.gitignore\)/);
  AGENTS.excluder = `${FIXED} appendFileSync(".git/info/exclude", "ruff.toml\\n"); writeFileSync("ruff.toml", "[lint]\\nignore = [\\"F401\\"]\\n");`;
  const excluded = loop(repository(), "--agent", agent("excluder").command);
  assert.equal(excluded.code, 1, excluded.output);
  assert.match(excluded.output, /the agent changed the checks themselves \(\.git\/info\/exclude\)/);
});

// The agent commits through tools/git-run.mjs, as the fixtures are built, so its commit can't flake.
const GIT_RUN = JSON.stringify(pathToFileURL(join(dirname(LOOP), "git-run.mjs")).href);
const COMMITTER = `${FIXED} writeFileSync("app.py", "import os  # noqa: F401\\n"); const { git } = await import(${GIT_RUN}); git(process.cwd(), ["add", "-A"]); git(process.cwd(), ["-c", "user.email=a@example.com", "-c", "user.name=a", "commit", "-q", "-m", "fix"]);`;

test("a commit stops the loop, even one that makes the checks pass", () => {
  const root = repository();
  const start = git(root, "rev-parse", "--short=7", "HEAD").trim();
  AGENTS.committer = COMMITTER;
  const { code, output } = loop(root, "--agent", agent("committer").command);
  assert.equal(code, 1, output);
  assert.match(output, new RegExp(`the agent moved HEAD from ${start} to [0-9a-f]{7}: it committed, or checked out another commit\\.`));
  assert.match(output, new RegExp(`Stopping: a person needs to review what changed since ${start}, where the loop started\\.`));
  assert.doesNotMatch(output, /pass after/);
});

test("the prompt says a commit stops the run", () => {
  const fake = agent("fixer");
  loop(repository(), "--agent", fake.command);
  assert.match(fake.prompt(), /Don't commit: leave your changes in the working tree\. A commit, or a checkout of another commit, stops the run too\./);
});
