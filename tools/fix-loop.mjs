// A headless fix loop for pipelines (chapter 25): run the fast checks, and while they fail, hand
// the report to an agent command and check again, at most three times.
//
//   node tools/fix-loop.mjs --agent "<command>" [--attempts N] [--record FILE]
//
// Run it from the repository root. The agent command runs through the shell with the prompt on
// stdin, the way `claude -p` and `codex exec` read one; the command is yours, so the shell is too.
// The loop stops early, and exits 1, when:
//   - the agent moved HEAD (it committed, or checked out another commit): everything below is
//     measured against the commit the loop started from, and the prompt says not to commit;
//   - the agent changed the checks themselves (tools/protected.mjs: every check's code and data, and
//     a tool's configuration file wherever it appears): a person decides that;
//   - the agent silenced a rule in the code, with a line tools/silenced.mjs recognizes (chapter 26);
//   - the agent changed what the checks compare the code with (REFERENCES, and the numbers the
//     documents claim): either side can be the wrong one, and a person decides which (chapter 34);
//   - an attempt leaves the checks reporting exactly what they reported before, because another
//     attempt would get the same prompt;
//   - the agent command didn't finish (it couldn't start, or ran past AGENT_TIMEOUT_MS).
// It never commits and never undoes what the agent changed: that's left for a person, or the
// pipeline's next step, to review. Exit codes: 0 the checks pass, 1 they don't, 2 usage.
//
// With --record FILE it appends one JSON line per attempt (chapter 26): which checks failed, what the
// attempt did about them (fixed, silenced a rule, changed the checks, changed a reference, no
// progress, still failing, didn't finish, moved HEAD), and the lines or files behind that. tools/measure.mjs
// counts them.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { failureReport, RERUN, RULES, runFastChecks } from "./feedback.mjs";
import { isProtected, PROTECTED } from "./protected.mjs";
import { newlyAdded, workingSilenced } from "./silenced.mjs";

// git's own files that decide what it lists and diffs: a pattern added to info/exclude hides a new
// file from the list below as surely as one added to a .gitignore, which PROTECTED names.
const GIT_OWN = ["info/exclude", "config"];
// git's empty tree: what a repository with no commit yet is compared with.
const EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
// What the checks compare the code with: the API contract and the types generated from it
// (chapter 7), and the numbers the documents claim after a <!-- claim: NAME --> marker (chapter 8).
// When one of those checks fails, the code may be wrong or the record may be, and bringing the
// record into line with the code makes the check pass either way. Which side is wrong is a
// person's call, so an attempt that changes one stops the loop (chapter 34).
const REFERENCES = [/^contracts\//, /^ts\/src\/api-types\.ts$/];
const CLAIMING = ["README.md", "AGENTS.md", "CLAUDE.md"];
const AGENT_TIMEOUT_MS = 20 * 60 * 1000;

function option(name) {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

// A hash of every protected file git can see, tracked or new, so a change made during the loop
// shows up whatever state the tree was in when it started; with the checks' own list, git's own
// ignore and configuration files too.
function protectedFiles(root, patterns = PROTECTED) {
  const listed = spawnSync("git", ["ls-files", "--cached", "--others", "--exclude-standard", "-z"], { cwd: root, encoding: "utf8" });
  const hashes = new Map();
  const hash = (path) => (existsSync(path) ? createHash("sha256").update(readFileSync(path)).digest("hex") : "deleted");
  for (const file of listed.stdout.split("\0").filter((f) => isProtected(f, patterns))) hashes.set(file, hash(join(root, file)));
  if (patterns === PROTECTED) {
    for (const name of GIT_OWN) {
      const path = spawnSync("git", ["rev-parse", "--git-path", name], { cwd: root, encoding: "utf8" }).stdout.trim();
      hashes.set(path.replaceAll("\\", "/"), hash(resolve(root, path)));
    }
  }
  return hashes;
}

// The commit checked out, or null before the first commit.
function head(root) {
  const run = spawnSync("git", ["rev-parse", "--verify", "--quiet", "HEAD"], { cwd: root, encoding: "utf8" });
  return run.status === 0 ? run.stdout.trim() : null;
}

// The references as they stand: a hash of each reference file, and each number a document claims,
// by the document and the claim's name. Only the numbers count: the prose around them is the
// agent's to fix like any other text.
function references(root) {
  const now = protectedFiles(root, REFERENCES);
  for (const doc of CLAIMING) {
    const path = join(root, doc);
    if (!existsSync(path)) continue;
    // As in tools/doc-claims.mjs, a marker inside a code span is an example, not a claim.
    for (const line of readFileSync(path, "utf8").split("\n")) {
      for (const m of line.replace(/`[^`]*`/g, "").matchAll(/<!--\s*claim:\s*([\w-]+)\s*-->\s*(\d[\d,]*)?/g)) {
        const key = `${doc}, the number it claims for ${m[1]}`;
        now.set(key, now.has(key) ? `${now.get(key)} ${m[2] ?? ""}` : (m[2] ?? ""));
      }
    }
  }
  return now;
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
    "So does switching a rule off in the code, with a comment that tells a linter, type checker or test runner to skip it.",
    "So does changing what the checks compare the code with: the API contract, the types made from it, or a number a document claims.",
    "Don't commit: leave your changes in the working tree. A commit, or a checkout of another commit, stops the run too.",
    `This is attempt ${attempt} of ${attempts}.`,
  ].join("\n");
}

// check.mjs prints how long each check took, which differs between identical runs.
const withoutTimes = (output) => output.replace(/\(\d+(\.\d+)?s\)/g, "");

// The checks a report names as failed, by their labels, without the times.
const failing = (output) =>
  output
    .replaceAll("\r\n", "\n")
    .split("\n")
    .filter((line) => line.startsWith("FAIL  "))
    .map((line) => line.slice(6).replace(/\s*\(\d+(\.\d+)?s\)\s*$/, "").trim());

// One line per attempt, for tools/measure.mjs.
function record(entry) {
  if (!recordTo) return;
  mkdirSync(dirname(recordTo), { recursive: true });
  appendFileSync(recordTo, `${JSON.stringify({ at: new Date().toISOString(), ...entry })}\n`);
}

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
  console.error(
    'Usage: node tools/fix-loop.mjs --agent "<command>" [--attempts N] [--record FILE], N from 1 to 10 (default 3).',
  );
  process.exit(2);
}
const root = process.cwd();
const recordTo = option("--record") ? resolve(root, option("--record")) : null;
if (!existsSync(join(root, "check.mjs"))) {
  console.error("fix-loop: run this from the repository root: there's no check.mjs here.");
  process.exit(2);
}
if (spawnSync("git", ["rev-parse", "--git-dir"], { cwd: root }).status !== 0) {
  console.error("fix-loop: this needs a git repository, to see what the agent changed.");
  process.exit(2);
}

// Everything an attempt did is measured against where the loop started, not against HEAD, which
// an agent can move.
const start = head(root);
const base = start ?? EMPTY_TREE;
const before = protectedFiles(root);
const referencesBefore = references(root);
let checks = runFastChecks(root);
if (checks.passed) {
  console.log("fix-loop: the fast checks already pass; nothing to do.");
  process.exit(0);
}
for (let attempt = 1; attempt <= attempts; attempt++) {
  console.log(`fix-loop: the fast checks fail. Attempt ${attempt} of ${attempts}: handing the report to the agent.`);
  const failed = failing(checks.output);
  const silencedBefore = workingSilenced(root, base);
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
    record({ attempt, failing: failed, outcome: "didn't finish", still_failing: failed, silenced: [], checks_changed: [], references_changed: [], head_moved: false });
    finish(root, 1, checks);
  }
  const seconds = Math.round((Date.now() - started) / 1000);
  console.log(`fix-loop: the agent exited ${run.status} after ${seconds}s.`);
  if (run.status !== 0 && run.stderr) console.log(excerpt(run.stderr));

  const now = head(root);
  const moved = now !== start;
  const changed = changedChecks(before, protectedFiles(root));
  const silenced = newlyAdded(silencedBefore, workingSilenced(root, base));
  const rewritten = changedChecks(referencesBefore, references(root));
  const previous = checks;
  checks = runFastChecks(root);
  const unchanged = withoutTimes(checks.output) === withoutTimes(previous.output);
  const outcome = moved
    ? "moved HEAD"
    : changed.length
      ? "changed the checks"
      : silenced.length
        ? "silenced a rule"
        : rewritten.length
          ? "changed a reference"
          : checks.passed
            ? "fixed"
            : unchanged
              ? "no progress"
              : "still failing";
  record({
    attempt,
    failing: failed,
    outcome,
    still_failing: failing(checks.output),
    silenced,
    checks_changed: changed,
    references_changed: rewritten,
    head_moved: moved,
  });
  if (moved) {
    const short = (commit) => (commit ? commit.slice(0, 7) : "no commit");
    console.log(`fix-loop: the agent moved HEAD from ${short(start)} to ${short(now)}: it committed, or checked out another commit.`);
    if (changed.length) console.log(`It changed the checks themselves: ${changed.join(", ")}.`);
    if (silenced.length) console.log(`It silenced a rule:\n${silenced.map((line) => `  ${line}`).join("\n")}`);
    if (rewritten.length) console.log(`It changed what the checks compare the code with: ${rewritten.join("; ")}.`);
    console.log(`Stopping: a person needs to review what changed since ${short(start)}, where the loop started.`);
    finish(root, 1, checks);
  }
  if (changed.length) {
    const passing = checks.passed ? ", and with that change they pass" : "";
    console.log(`fix-loop: the agent changed the checks themselves (${changed.join(", ")})${passing}. Stopping: a person needs to review that.`);
    finish(root, 1, checks);
  }
  if (silenced.length) {
    const passing = checks.passed ? ", and with that the checks pass" : "";
    console.log(`fix-loop: the agent silenced a rule instead of fixing the code${passing}:`);
    for (const line of silenced) console.log(`  ${line}`);
    console.log("Stopping: a person needs to review that.");
    finish(root, 1, checks);
  }
  if (rewritten.length) {
    const passing = checks.passed ? ", and with that the checks pass" : "";
    console.log(`fix-loop: the agent changed what the checks compare the code with (${rewritten.join("; ")})${passing}.`);
    console.log("Stopping: the code may be what's wrong, and a person decides which side to change.");
    finish(root, 1, checks);
  }
  if (checks.passed) {
    console.log(`fix-loop: the fast checks pass after ${attempt} attempt${attempt === 1 ? "" : "s"}.`);
    finish(root, 0, checks);
  }
  if (unchanged) {
    console.log(`fix-loop: no progress: after attempt ${attempt} the checks report exactly what they did before. Stopping.`);
    finish(root, 1, checks);
  }
}
console.log(`fix-loop: the fast checks still fail after ${attempts} attempts. Stopping: a person needs to look.`);
finish(root, 1, checks);
