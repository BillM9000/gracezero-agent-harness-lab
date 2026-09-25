// Tests for tools/measure.mjs (chapter 26). Each test builds a small git repository with set dates,
// authors and co-author trailers, and sometimes a records folder, then checks what it measures.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { change, ciMeasures, describe, loopMeasures, main, measure, reviewMeasures, spendMeasures } from "./measure.mjs";

const made = [];
after(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

const DAY = 24 * 60 * 60 * 1000;
const START = Date.parse("2026-01-01T12:00:00Z");
const AGENT_TRAILER = "\n\nCo-Authored-By: Claude <noreply@anthropic.com>";
const at = (day) => new Date(START + day * DAY).toISOString();

// commits: [{ day, subject, files: { path: content }, agent: true | undefined, tag }]
function repository(commits) {
  const root = mkdtempSync(join(tmpdir(), "measure-"));
  made.push(root);
  spawnSync("git", ["init", "-q"], { cwd: root });
  const hashes = [];
  for (const c of commits) {
    for (const [path, content] of Object.entries(c.files)) {
      mkdirSync(dirname(join(root, path)), { recursive: true });
      writeFileSync(join(root, path), content);
    }
    const message = c.subject + (c.agent ? AGENT_TRAILER : "");
    spawnSync("git", ["add", "-A"], { cwd: root });
    const commit = spawnSync("git", ["-c", "user.name=A Person", "-c", "user.email=someone@example.com", "commit", "-q", "-m", message], {
      cwd: root,
      env: { ...process.env, GIT_AUTHOR_DATE: at(c.day), GIT_COMMITTER_DATE: at(c.day) },
    });
    assert.equal(commit.status, 0, String(commit.stderr));
    hashes.push(spawnSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).stdout.trim());
    if (c.tag) spawnSync("git", ["tag", c.tag], { cwd: root });
  }
  return { root, hashes };
}

const measured = (root, options = {}) => measure(root, { records: join(root, "records"), ...options }).result;

test("agent changes and rework are counted the way tools/rework.mjs counts them", () => {
  const { root } = repository([
    { day: 1, subject: "feat: the form", files: { "src/form.js": "1" }, agent: true },
    { day: 2, subject: "fix: the form's last field", files: { "src/form.js": "2" } },
    { day: 3, subject: "feat: a person's page", files: { "src/page.js": "1" } },
    { day: 4, subject: "fix: the person's page", files: { "src/page.js": "2" } },
  ]);
  const m = measured(root);
  assert.deepEqual([m.commits, m.agentChanges, m.reworkFixes, m.medianHoursToFix], [4, 1, 1, 24]);
});

test("a revert of recent agent work is a revert; a revert of a person's change isn't counted", () => {
  const { root } = repository([
    { day: 1, subject: "feat: the export", files: { "src/export.js": "1" }, agent: true },
    { day: 2, subject: 'Revert "feat: the export"', files: { "src/export.js": "0" } },
    { day: 3, subject: "feat: a person's import", files: { "src/import.js": "1" } },
    { day: 4, subject: 'Revert "feat: a person\'s import"', files: { "src/import.js": "0" } },
  ]);
  const m = measured(root);
  assert.deepEqual([m.reworkFixes, m.reverts], [1, 1]);
});

test("lines that silence a rule count only in agent changes", () => {
  const { root } = repository([
    { day: 1, subject: "feat: the agent's module", files: { "app/a.py": "import os  # noqa: F401\n" }, agent: true },
    { day: 2, subject: "feat: a person's module", files: { "app/b.py": "import os  # noqa: F401\n" } },
    { day: 3, subject: "docs: the agent's notes", files: { "NOTES.md": "Use # noqa sparingly.\n" }, agent: true },
  ]);
  const { result, silencedLines } = measure(root, {});
  assert.equal(result.silenced, 1);
  assert.deepEqual(silencedLines, ["app/a.py: import os  # noqa: F401"]);
});

test("a fix to documentation alone is a drift fix; a fix to code and documentation isn't", () => {
  const { root } = repository([
    { day: 1, subject: "feat: setup", files: { "setup.js": "1", "README.md": "Run setup" }, agent: true },
    { day: 2, subject: "fix: the README's setup steps", files: { "README.md": "Run node setup.mjs" } },
    { day: 3, subject: "fix: setup and its README", files: { "setup.js": "2", "README.md": "Run it twice" } },
  ]);
  assert.equal(measured(root).driftFixes, 1);
});

test("a known failure counts every fix whose subject names it, rework or not", () => {
  const { root } = repository([
    { day: 1, subject: "feat: dates", files: { "src/dates.js": "1" }, agent: true },
    { day: 2, subject: "fix: dates in the wrong time zone", files: { "src/dates.js": "2" } },
    { day: 30, subject: "fix: Time Zone of the export", files: { "src/export.js": "1" } },
    { day: 31, subject: "feat: a time zone picker", files: { "src/picker.js": "1" } },
  ]);
  assert.deepEqual(measured(root, { known: ["time zone"] }).known, { "time zone": 2 });
});

test("the window ends at --at and reaches back --days", () => {
  const { root } = repository([
    { day: 1, subject: "feat: old", files: { "a.js": "1" }, agent: true },
    { day: 20, subject: "feat: before", files: { "b.js": "1" }, agent: true, tag: "baseline" },
    { day: 21, subject: "feat: after", files: { "c.js": "1" }, agent: true },
  ]);
  const m = measured(root, { rev: "baseline", days: 10 });
  assert.deepEqual([m.commits, m.agentChanges, m.end.date], [1, 1, at(20).slice(0, 10)]);
});

test("CI's pass rate counts runs on agent changes that finished with a verdict on the code", () => {
  const agent = new Set(["a1", "a2", "a3"]);
  const runs = [
    { headSha: "a1", conclusion: "success" },
    { headSha: "a2", conclusion: "failure" },
    { headSha: "a3", conclusion: "cancelled" },
    { headSha: "a3", conclusion: "timed_out" },
    { headSha: "p1", conclusion: "failure" },
  ];
  assert.deepEqual(ciMeasures(runs, agent), { runs: 3, passed: 1 });
});

test("review time is the median, opened to merged, of pull requests with an agent change merged in the window", () => {
  const agent = new Set(["m1", "c2", "m4"]);
  const pr = (created, merged, merge, commits = []) => ({ createdAt: at(created), mergedAt: at(merged), mergeCommit: { oid: merge }, commits: commits.map((oid) => ({ oid })) });
  const prs = [
    pr(1, 1.25, "m1"), // 6 hours, the squash commit is the agent's
    pr(2, 2.5, "x2", ["c2"]), // 12 hours, a branch commit is the agent's
    pr(3, 3.1, "p3"), // a person's
    pr(0, 40, "m4"), // merged after the window
    { createdAt: at(5), mergedAt: null, mergeCommit: null, commits: [] }, // never merged
  ];
  const start = Date.parse(at(0)) / 1000;
  const end = Date.parse(at(30)) / 1000;
  assert.deepEqual(reviewMeasures(prs, agent, start, end), { prs: 2, medianHours: 9 });
});

test("spend inside the window is summed; spend outside it isn't", () => {
  const lines = [
    { at: at(1), usd: 2 },
    { at: at(2), usd: 3 },
    { at: at(40), usd: 100 },
    { at: at(3), note: "no usd" },
  ];
  assert.deepEqual(spendMeasures(lines, Date.parse(at(0)) / 1000, Date.parse(at(30)) / 1000), { lines: 2, usd: 5 });
});

test("the loop's record counts each attempt by what it did", () => {
  const entries = [
    { outcome: "fixed", failing: ["Python lint (ruff check)"] },
    { outcome: "silenced a rule", failing: ["Python lint (ruff check)"] },
    { outcome: "changed the checks", failing: ["Agent definitions (python -m agent_policy)"] },
    { outcome: "no progress", failing: ["Agent definitions (python -m agent_policy)"] },
  ];
  const m = loopMeasures(entries);
  assert.deepEqual([m.attempts, m.fixed, m.silencedOrChanged, m.other], [4, 1, 2, 1]);
  assert.equal(m.byCheck["Python lint (ruff check)"], 2);
});

test("a change in a rate is called only with 30 or more on a side, and only when its interval leaves out zero", () => {
  const big = change(14, 40, 4, 40);
  assert.deepEqual([Math.round(100 * big.d), Math.round(100 * big.low), Math.round(100 * big.high)], [-25, -42, -8]);
  assert.equal(change(10, 20, 5, 20).tooFew, true);
  const small = change(12, 40, 10, 40);
  assert.ok(small.low < 0 && small.high > 0);
  assert.match(describe("Rework", small), /: within noise.$/);
  assert.match(describe("Rework", big), /: more than noise.$/);
  assert.match(describe("Rework", change(10, 20, 5, 20)), /fewer than 30 on a side/);
});

test("--against reports both windows, uses the baseline's length and known failures, and says what's noise", () => {
  const commits = [];
  for (let i = 0; i < 30; i++) commits.push({ day: i * 0.4, subject: `feat: ${i}`, files: { [`a/${i}.js`]: "1" }, agent: true });
  for (let i = 0; i < 12; i++) commits.push({ day: i * 0.4 + 0.1, subject: `fix: ${i} in the time zone`, files: { [`a/${i}.js`]: "2" } });
  commits.sort((x, y) => x.day - y.day);
  commits.at(-1).tag = "before";
  for (let i = 0; i < 30; i++) commits.push({ day: 13 + i * 0.4, subject: `feat: b${i}`, files: { [`b/${i}.js`]: "1" }, agent: true });
  const { root } = repository(commits);
  const saved = join(root, "records", "baseline.json");
  main([root, "--at", "before", "--days", "12", "--known", "time zone", "--save", saved]);
  const out = main([root, "--against", saved]);
  assert.match(out.split("\n")[0], /the 12 days up to/);
  assert.match(out, /rework fixes per agent change +12 \(40%\) +0 \(0%\)/);
  assert.match(out, /known failure: "time zone" +12 +0/);
  assert.match(out, /Rework per agent change: down 40 points \(95% interval -58 to -22\): more than noise\./);
  assert.equal(JSON.parse(readFileSync(saved, "utf8")).days, 12);
});

test("a records folder is optional, and says what wasn't measured", () => {
  const { root } = repository([{ day: 1, subject: "feat: x", files: { "x.js": "1" }, agent: true }]);
  const out = main([root]);
  assert.match(out, /CI pass rate on agent changes +not measured: no .*records\/ci-runs\.json/);
  mkdirSync(join(root, "records"));
  writeFileSync(join(root, "records", "fix-loop.jsonl"), `${JSON.stringify({ outcome: "fixed", failing: ["x"] })}\n`);
  assert.match(main([root]), /violations sent back to an agent +1\n {2}its next change fixed the code +1/);
});
