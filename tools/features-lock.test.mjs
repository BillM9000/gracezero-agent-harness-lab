// Tests for tools/features-lock.mjs (Appendix B's locked spec): a spec whose every feature has a
// decided decision and a test that exists passes, its states document is written only then, and
// each planted break fails with what to do. Each test builds a small folder, not a git repository,
// so every file in it counts as the repository's.
// Run: node --test tools/features-lock.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

const LOCK = join(dirname(fileURLToPath(import.meta.url)), "features-lock.mjs");
const base = mkdtempSync(join(tmpdir(), "lock-"));
after(() => rmSync(base, { recursive: true, force: true }));

const TEST_FILE = 'import { test } from "node:test";\ntest("exports the report", () => {});\ntest("imports it back", () => {});\n';
const gap = (id, decision = "Yes.") => ({ id, question: `${id}?`, found_by: ["a person"], decides: "owner", decision, by: decision ? "Dana" : null, on: decision ? "2026-09-30" : null });
const feature = (id, fields = {}) => ({
  id,
  description: `Feature ${id}.`,
  status: "done",
  decision: "G1",
  proof: "tests/report.test.mjs::exports the report",
  ...fields,
});

let n = 0;
function project(features, gaps = [gap("G1"), gap("G2")]) {
  const root = join(base, `case-${++n}`);
  const files = {
    "tests/report.test.mjs": TEST_FILE,
    "spec/gaps.json": JSON.stringify({ about: "a", brief: "brief.md", gaps }),
    "spec/features.json": JSON.stringify({ about: "a", decisions: "gaps.json", states: "states.md", features }),
  };
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  return root;
}
const edit = (root, change) => {
  const path = join(root, "spec", "features.json");
  const spec = JSON.parse(readFileSync(path, "utf8"));
  change(spec);
  writeFileSync(path, JSON.stringify(spec));
};
function lock(root, ...args) {
  const run = spawnSync(process.execPath, [LOCK, join("spec", "features.json"), ...args], { cwd: root, encoding: "utf8" });
  return { status: run.status, output: `${run.stdout}${run.stderr}` };
}

test("a locked spec passes once its states document is written, and --write writes it", () => {
  const root = project([feature("F1"), feature("F2", { status: "todo", decision: "G2", proof: "tests/report.test.mjs::imports it back" })]);
  const before = lock(root);
  assert.equal(before.status, 1, before.output);
  assert.match(before.output, /states\.md isn't what features\.json says now \(it doesn't exist\)\. Run node tools\/features-lock\.mjs spec[\\/]features\.json --write/);
  const written = lock(root, "--write");
  assert.equal(written.status, 0, written.output);
  assert.match(written.output, /Wrote states\.md\./);
  const states = readFileSync(join(root, "spec", "states.md"), "utf8");
  assert.match(states, /^# Feature states\n/);
  assert.match(states, /^\| F1 \| Feature F1\. \| done \| G1 \| `tests\/report\.test\.mjs::exports the report` \|$/m);
  assert.match(states, /^Done 1, in progress 0, to do 1, dropped 0\.$/m);
  const after = lock(root);
  assert.equal(after.status, 0, after.output);
  assert.match(after.output, /2 feature\(s\), each with a decision and, unless dropped, a proof test that exists\./);
});

test("a changed spec makes the states document stale until it's written again", () => {
  const root = project([feature("F1")]);
  assert.equal(lock(root, "--write").status, 0);
  edit(root, (spec) => (spec.features[0].status = "in-progress"));
  const stale = lock(root);
  assert.equal(stale.status, 1);
  assert.match(stale.output, /states\.md isn't what features\.json says now\. Run/);
  assert.equal(lock(root, "--write").status, 0);
  assert.equal(lock(root).status, 0);
});

test("a feature with no proof test, or one that doesn't exist, fails, unless it's dropped", () => {
  const cases = [
    [{ proof: null }, /F1: has no proof test\. Name the test that proves it/],
    [{ proof: "" }, /F1: has no proof test/],
    [{ proof: "tests/report.test.mjs::sends the report" }, /F1: its proof names sends the report, which isn't a test in tests\/report\.test\.mjs\. Write the test first/],
    [{ proof: "tests/gone.test.mjs::exports the report" }, /F1: its proof file, tests\/gone\.test\.mjs, isn't in the repository/],
    [{ proof: "README.md" }, /"README\.md" isn't a proof\. Write it as <test file>::<test name>/],
  ];
  for (const [fields, message] of cases) {
    const root = project([feature("F1", fields)]);
    const run = lock(root, "--write");
    assert.equal(run.status, 1, run.output);
    assert.match(run.output, message);
    assert.match(run.output, /states\.md wasn't written: the spec must pass its lock first\./);
    assert.equal(existsSync(join(root, "spec", "states.md")), false);
  }
  const dropped = project([feature("F1", { status: "dropped", proof: null })]);
  assert.equal(lock(dropped, "--write").status, 0);
});

test("a feature needs a decision that the record has, and that is decided", () => {
  const cases = [
    [[feature("F1", { decision: null })], undefined, /F1: names no decision\. Every feature rests on a decision in gaps\.json/],
    [[feature("F1", { decision: "G9" })], undefined, /F1: its decision, G9, isn't in gaps\.json/],
    [[feature("F1")], [gap("G1", null)], /F1: its decision, G1, is still open in gaps\.json\. Decide it before the feature is locked/],
  ];
  for (const [features, gaps, message] of cases) {
    const run = lock(project(features, gaps));
    assert.equal(run.status, 1, run.output);
    assert.match(run.output, message);
  }
});

test("a locked id stays: removing or renaming a feature fails, and dropping it passes", () => {
  const root = project([feature("F1"), feature("F2", { proof: "tests/report.test.mjs::imports it back" })]);
  assert.equal(lock(root, "--write").status, 0);
  edit(root, (spec) => spec.features.pop());
  const gone = lock(root, "--write");
  assert.equal(gone.status, 1, gone.output);
  assert.match(gone.output, /F2 was locked \(states\.md lists it\) and is gone\. A locked feature keeps its id: set its status to dropped/);
  edit(root, (spec) => spec.features.push(feature("F3", { proof: "tests/report.test.mjs::imports it back" })));
  assert.match(lock(root).output, /F2 was locked/);
  edit(root, (spec) => {
    spec.features.pop();
    spec.features.push(feature("F2", { status: "dropped", decision: "G2", proof: null }));
  });
  assert.equal(lock(root, "--write").status, 0);
  assert.match(readFileSync(join(root, "spec", "states.md"), "utf8"), /^\| F2 \| Feature F2\. \| dropped \| G2 \| none \|$/m);
});

test("malformed features, repeated ids and placeholders are refused", () => {
  const cases = [
    [[feature("F1"), feature("F1")], /F1: another feature has the same id\. Ids are never reused\./],
    [[feature("1")], /its id must be F and a number/],
    [[feature("F1", { status: "shipped" })], /its status is "shipped"; use one of todo, in-progress, done, dropped/],
    [[feature("F1", { owner: "Sam" })], /unknown field\(s\) owner/],
    [[feature("F1", { description: "<What it does.>" })], /"<What it does\.>" is still a placeholder/],
  ];
  for (const [features, message] of cases) {
    const run = lock(project(features));
    assert.equal(run.status, 1, run.output);
    assert.match(run.output, message);
  }
  const root = project([feature("F1")]);
  writeFileSync(join(root, "spec", "features.json"), "{");
  assert.equal(lock(root).status, 2);
});
