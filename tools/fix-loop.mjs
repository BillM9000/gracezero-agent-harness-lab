// A headless fix loop for pipelines (chapter 25): run the fast checks, and while they fail, hand
// the report to an agent command and check again, at most three times.
//
//   node tools/fix-loop.mjs --agent "<command>" [--attempts N]
//
// Run it from the repository root. The agent command runs through the shell with the prompt on
// stdin, the way `claude -p` and `codex exec` read one; the command is yours, so the shell is too.
// The loop stops early, and exits 1, when:
//   - the agent moved HEAD (it committed, or checked out another commit), which the prompt says not
//     to do: its changes would leave the working tree a person reviews;
//   - the agent changed the checks themselves (tools/protected.mjs: every check's code and data, and
//     a tool's configuration file wherever it appears): a person decides that;
//   - an attempt leaves the checks reporting exactly what they reported before, because another
//     attempt would get the same prompt;
//   - the agent command didn't finish (it couldn't start, or ran past AGENT_TIMEOUT_MS).
// It never commits and never undoes what the agent changed: that's left for a person, or the
// pipeline's next step, to review. Exit codes: 0 the checks pass, 1 they don't, 2 usage.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { failureReport, RERUN, RULES, runFastChecks } from "./feedback.mjs";
import { isProtected } from "./protected.mjs";

// git's own files that decide what it lists and diffs: a pattern added to info/exclude hides a new
// file from the list below as surely as one added to a .gitignore, which the protected list names.
const GIT_OWN = ["info/exclude", "config"];
const AGENT_TIMEOUT_MS = 20 * 60 * 1000;

function option(name) {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

// A hash of every protected file git can see, tracked or new, so a change made during the loop
// shows up whatever state the tree was in when it started; git's own ignore and configuration
// files too.
function protectedFiles(root) {
  const listed = spawnSync("git", ["ls-files", "--cached", "--others", "--exclude-standard", "-z"], { cwd: root, encoding: "utf8" });
  const hashes = new Map();
  const hash = (path) => (existsSync(path) ? createHash("sha256").update(readFileSync(path)).digest("hex") : "deleted");
  for (const file of listed.stdout.split("\0").filter((f) => isProtected(f))) hashes.set(file, hash(join(root, file)));
  for (const name of GIT_OWN) {
    const path = spawnSync("git", ["rev-parse", "--git-path", name], { cwd: root, encoding: "utf8" }).stdout.trim();
    hashes.set(path.replaceAll("\\", "/"), hash(resolve(root, path)));
  }
  return hashes;
}

// The commit checked out, or null before the first commit.
function head(root) {
  const run = spawnSync("git", ["rev-parse", "--verify", "--quiet", "HEAD"], { cwd: root, encoding: "utf8" });
  return run.status === 0 ? run.stdout.trim() : null;
}

function changedChecks(before, after) {
  const files = new Set([...before.keys(), ...after.keys()]);
  return [...files].filter((file) => before.get(file) !== after.get(file)).sort();
}

function promptFor(output, attempt, attempts) {
  return [
    "The fast checks in this repository fail. Make them pass.",
    "",
    failureReport(output),
    "",
    `Run them with: ${RERUN}`,
    ...RULES,
    "Changing the checks themselves (tests, lint rules, check scripts or their settings) stops this run for a person to review.",
    "Don't commit: leave your changes in the working tree. A commit, or a checkout of another commit, stops the run too.",
    `This is attempt ${attempt} of ${attempts}.`,
  ].join("\n");
}

// check.mjs prints how long each check took, which differs between identical runs.
const withoutTimes = (output) => output.replace(/\(\d+(\.\d+)?s\)/g, "");

// An error's message often comes first in what a command prints, and a summary last: keep both.
function excerpt(text) {
  const lines = text.trimEnd().split("\n");
  return lines.length <= 20 ? lines.join("\n") : [...lines.slice(0, 10), "...", ...lines.slice(-10)].join("\n");
}

function finish(root, code, checks) {
  if (!checks.passed) console.log(`\nWhat the checks still report:\n${failureReport(checks.output)}`);
  const status = spawnSync("git", ["status", "--short"], { cwd: root, encoding: "utf8" }).stdout.trimEnd();
  console.log(status ? `\nLeft in the working tree for review:\n${status}` : "\nThe working tree has no changes.");
  process.exit(code);
}

const agent = option("--agent");
const attempts = Number(option("--attempts") ?? 3);
if (!agent || !Number.isInteger(attempts) || attempts < 1 || attempts > 10) {
  console.error('Usage: node tools/fix-loop.mjs --agent "<command>" [--attempts N], N from 1 to 10 (default 3).');
  process.exit(2);
}
const root = process.cwd();
if (!existsSync(join(root, "check.mjs"))) {
  console.error("fix-loop: run this from the repository root: there's no check.mjs here.");
  process.exit(2);
}
if (spawnSync("git", ["rev-parse", "--git-dir"], { cwd: root }).status !== 0) {
  console.error("fix-loop: this needs a git repository, to see what the agent changed.");
  process.exit(2);
}

// Where the loop started: an attempt that moves HEAD, by committing or checking out another commit,
// stops the loop.
const start = head(root);
const before = protectedFiles(root);
let checks = runFastChecks(root);
if (checks.passed) {
  console.log("fix-loop: the fast checks already pass; nothing to do.");
  process.exit(0);
}
for (let attempt = 1; attempt <= attempts; attempt++) {
  console.log(`fix-loop: the fast checks fail. Attempt ${attempt} of ${attempts}: handing the report to the agent.`);
  const started = Date.now();
  const run = spawnSync(agent, {
    cwd: root,
    shell: true,
    input: promptFor(checks.output, attempt, attempts),
    encoding: "utf8",
    timeout: AGENT_TIMEOUT_MS,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (run.stdout) process.stdout.write(run.stdout);
  if (run.error) {
    console.log(`fix-loop: the agent command didn't finish (${run.error.message}). Stopping.`);
    finish(root, 1, checks);
  }
  const seconds = Math.round((Date.now() - started) / 1000);
  console.log(`fix-loop: the agent exited ${run.status} after ${seconds}s.`);
  if (run.status !== 0 && run.stderr) console.log(excerpt(run.stderr));

  const now = head(root);
  const moved = now !== start;
  const changed = changedChecks(before, protectedFiles(root));
  const previous = checks;
  checks = runFastChecks(root);
  if (moved) {
    const short = (commit) => (commit ? commit.slice(0, 7) : "no commit");
    console.log(`fix-loop: the agent moved HEAD from ${short(start)} to ${short(now)}: it committed, or checked out another commit.`);
    if (changed.length) console.log(`It changed the checks themselves: ${changed.join(", ")}.`);
    console.log(`Stopping: a person needs to review what changed since ${short(start)}, where the loop started.`);
    finish(root, 1, checks);
  }
  if (changed.length) {
    const passing = checks.passed ? ", and with that change they pass" : "";
    console.log(`fix-loop: the agent changed the checks themselves (${changed.join(", ")})${passing}. Stopping: a person needs to review that.`);
    finish(root, 1, checks);
  }
  if (checks.passed) {
    console.log(`fix-loop: the fast checks pass after ${attempt} attempt${attempt === 1 ? "" : "s"}.`);
    finish(root, 0, checks);
  }
  if (withoutTimes(checks.output) === withoutTimes(previous.output)) {
    console.log(`fix-loop: no progress: after attempt ${attempt} the checks report exactly what they did before. Stopping.`);
    finish(root, 1, checks);
  }
}
console.log(`fix-loop: the fast checks still fail after ${attempts} attempts. Stopping: a person needs to look.`);
finish(root, 1, checks);
