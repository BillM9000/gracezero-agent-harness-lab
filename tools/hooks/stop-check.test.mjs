// Tests for the Stop hook (tools/hooks/stop-check.mjs and stop-decision.mjs, chapter 25). Each
// session runs the real hook script against a small folder whose check.mjs passes or fails, and
// keeps its count in a temporary folder, the way Claude Code would run it after every stop.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { decide, MAX_BLOCKS, repositoryRoot, stateFile } from "./stop-decision.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const LAB = resolve(HERE, "..", "..");
const HOOK = join(HERE, "stop-check.mjs");
const made = [];
after(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

function temporary(prefix) {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  made.push(dir);
  return dir;
}

// A folder whose check.mjs passes, or fails with a report shaped like the real one.
function project(passes) {
  const root = temporary("stop-project-");
  const failing = 'console.log("FAIL  Stub tests (0.2s)\\n      expected 2, got 3\\n\\n1 of 2 checks failed.");\nprocess.exit(1);\n';
  writeFileSync(join(root, "check.mjs"), `console.log("PASS  Stub lint (0.1s)");\n${passes ? "" : failing}`);
  mkdirSync(join(root, "python"));
  return root;
}

// Runs the hook the way the agent would: its input on stdin, in its own process.
function stop(root, stateDir, { session = "s1", active = false, hook = HOOK } = {}) {
  const input = JSON.stringify({ session_id: session, hook_event_name: "Stop", stop_hook_active: active, cwd: root });
  const run = spawnSync(process.execPath, [hook], { input, encoding: "utf8", env: { ...process.env, LAB_HOOK_STATE_DIR: stateDir } });
  return { code: run.status, stdout: run.stdout, stderr: run.stderr };
}

test("checks that pass let the agent stop, with nothing printed", () => {
  const result = stop(project(true), temporary("stop-state-"));
  assert.deepEqual(result, { code: 0, stdout: "", stderr: "" });
});

test("a failure blocks with exit code 2 and sends back what failed, how to rerun it and the rules", () => {
  const result = stop(project(false), temporary("stop-state-"));
  assert.equal(result.code, 2);
  assert.equal(result.stdout, "");
  assert.match(result.stderr, /^The fast checks failed, so the work isn't finished \(round 1 of 3\)\./);
  assert.match(result.stderr, /FAIL {2}Stub tests \(0\.2s\)\n {6}expected 2, got 3/);
  assert.doesNotMatch(result.stderr, /PASS/);
  assert.match(result.stderr, /Run them again with: node check\.mjs --fast/);
  assert.match(result.stderr, /Don't weaken or skip a test, a rule or a check to make it pass\./);
});

test("after three blocks in a row, lets the agent stop and tells the person", () => {
  const root = project(false);
  const state = temporary("stop-state-");
  const rounds = [stop(root, state), stop(root, state, { active: true }), stop(root, state, { active: true })];
  assert.deepEqual(rounds.map((r) => r.code), [2, 2, 2]);
  assert.match(rounds[2].stderr, /round 3 of 3/);
  const fourth = stop(root, state, { active: true });
  assert.equal(fourth.code, 0);
  assert.deepEqual(JSON.parse(fourth.stdout), {
    systemMessage:
      "The fast checks still fail after 3 rounds of fixes, so the agent was allowed to stop. Run node check.mjs --fast to see what's left.",
  });
});

test("a stop that doesn't follow a block starts counting again", () => {
  const root = project(false);
  const state = temporary("stop-state-");
  stop(root, state);
  assert.match(stop(root, state, { active: true }).stderr, /round 2 of 3/);
  assert.match(stop(root, state, { active: false }).stderr, /round 1 of 3/);
});

test("each session keeps its own count", () => {
  const root = project(false);
  const state = temporary("stop-state-");
  stop(root, state, { session: "a" });
  stop(root, state, { session: "a", active: true });
  assert.match(stop(root, state, { session: "b", active: true }).stderr, /round 1 of 3/);
  assert.match(stop(root, state, { session: "a", active: true }).stderr, /round 3 of 3/);
});

test("a session id can't choose where the count is written", () => {
  const dir = temporary("stop-state-");
  const file = stateFile("../../escape\\x", dir);
  assert.equal(dirname(file), dir);
  assert.equal(file, join(dir, "stop-______escape_x.json"));
  assert.equal(stateFile("", dir), join(dir, "stop-unknown.json"));
});

test("the checks run in the repository around the agent's working folder", () => {
  const root = project(true);
  assert.equal(repositoryRoot(join(root, "python")), root);
  assert.equal(repositoryRoot(root), root);
});

test("the decision never blocks on checks that passed, whatever the count", () => {
  for (const blocksSoFar of [0, 1, MAX_BLOCKS, MAX_BLOCKS + 5]) {
    assert.deepEqual(decide({ passed: true, output: "", blocksSoFar }), { exitCode: 0, blocks: 0 });
  }
});

// .claude/settings.json is what makes Claude Code run the hook. A mistyped path there doesn't
// fail anything visible: the hook can't start, Claude Code reports a non-blocking error, and the
// agent stops unchecked. So run each configured command the way Claude Code would.
test("every command hook in .claude/settings.json starts and gives a decision", () => {
  const settings = JSON.parse(readFileSync(join(LAB, ".claude", "settings.json"), "utf8"));
  const handlers = Object.values(settings.hooks).flat().flatMap((group) => group.hooks);
  assert.ok(handlers.length > 0, "no hooks configured");
  assert.ok(settings.hooks.Stop, "no Stop hook configured");
  for (const handler of handlers) {
    assert.equal(handler.type, "command");
    assert.equal(handler.command, "node");
    const script = handler.args[0].replace("${CLAUDE_PROJECT_DIR}", LAB);
    assert.ok(existsSync(script), `${handler.args[0]} doesn't exist`);
    assert.ok(handler.timeout <= 300, "a hung check would hold the agent for the full default of 600 seconds");
    const result = stop(project(true), temporary("stop-state-"), { hook: script });
    assert.equal(result.code, 0, result.stderr);
  }
});
