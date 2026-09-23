// Tests for tools/fix-loop.mjs (chapter 25). Each test builds a small git repository whose
// check.mjs fails while app.txt says "bug", then runs the loop with a scripted fake agent: one
// that fixes it, one that never manages to, one that does nothing, one that edits the check.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

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

function git(root, ...args) {
  return spawnSync("git", ["-c", "user.email=test@example.com", "-c", "user.name=test", ...args], { cwd: root, encoding: "utf8" });
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
    `import { existsSync, readFileSync, writeFileSync } from "node:fs";\n` +
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
  assert.match(git(root, "status", "--short").stdout, /M check\.mjs/);
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
