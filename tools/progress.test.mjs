// Proves the work-list check fails when "done" isn't backed by a test, when more than one item is
// in progress, and when an item is malformed, and that it shows a cold session what comes next.
// Run: node --test tools/progress.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "progress.mjs");
const base = mkdtempSync(join(tmpdir(), "progress-"));
after(() => rmSync(base, { recursive: true, force: true }));

const TESTS = {
  "python/tests/test_app.py": "def test_it_works():\n    assert True\n",
  "tools/a.test.mjs": 'test("the script counts", () => {});\n',
};

let n = 0;
function repo(features, extra = {}) {
  const root = join(base, `repo-${++n}`);
  const files = { ...TESTS, "progress/features.json": typeof features === "string" ? features : JSON.stringify({ features }), ...extra };
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  return root;
}

function check(root) {
  const run = spawnSync(process.execPath, [SCRIPT, root], { encoding: "utf8" });
  return { status: run.status, output: `${run.stdout}${run.stderr}` };
}

const done = (id, proof) => ({ id, description: `The ${id} works.`, status: "done", proof });
const todo = (id) => ({ id, description: `Build ${id}.`, status: "todo", proof: null });

test("a list whose done items name real tests passes, and shows what comes next", () => {
  const { status, output } = check(
    repo([done("app", "python/tests/test_app.py::test_it_works"), done("script", "tools/a.test.mjs::the script counts"), todo("next-thing"), todo("later")]),
  );
  assert.equal(status, 0, output);
  assert.match(output, /Done 2, in progress 0, to do 2\./);
  assert.match(output, /Next: next-thing: Build next-thing\./);
});

test("an item in progress comes before any item to do", () => {
  const busy = { id: "busy", description: "Half built.", status: "in-progress", proof: null };
  const { output } = check(repo([todo("first"), busy]));
  assert.match(output, /Next: busy: Half built\./);
});

test("an item marked done with no proof fails", () => {
  const { status, output } = check(repo([done("app", null)]));
  assert.equal(status, 1);
  assert.match(output, /app: is marked done but names no proof\. Add the test that shows it works, or set it back to in-progress\./);
});

test("a proof that names a missing test or file fails", () => {
  const items = [
    done("app", "python/tests/test_app.py::test_it_flies"),
    done("script", "tools/a.test.mjs::the script flies"),
    done("gone", "python/tests/test_gone.py::test_x"),
  ];
  const { status, output } = check(repo(items));
  assert.equal(status, 1);
  assert.match(output, /app: is marked done, but its proof names test_it_flies, which isn't a test in python\/tests\/test_app\.py\./);
  assert.match(output, /script: is marked done, but its proof names the script flies, which isn't a test in tools\/a\.test\.mjs\./);
  assert.match(output, /gone: is marked done, but its proof file, python\/tests\/test_gone\.py, isn't in the repository\./);
});

test("only one item may be in progress", () => {
  const busy = (id) => ({ id, description: "Half built.", status: "in-progress", proof: null });
  const { status, output } = check(repo([busy("one"), busy("two")]));
  assert.equal(status, 1);
  assert.match(output, /2 items are in progress \(one, two\)\. Work on one at a time/);
});

test("malformed items, duplicate ids and unknown statuses fail", () => {
  const items = [todo("same"), todo("same"), { id: "Bad Id", description: "", status: "finished" }];
  const { status, output } = check(repo(items));
  assert.equal(status, 1);
  assert.match(output, /same: another item has the same id\./);
  assert.match(output, /Bad Id: needs an id in lowercase words joined by hyphens\./);
  assert.match(output, /Bad Id: needs a description\./);
  assert.match(output, /Bad Id: its status is "finished"; use one of todo, in-progress, done\./);
});

test("a list that isn't valid JSON fails with the parser's message", () => {
  const { status, output } = check(repo('{ "features": [ '));
  assert.equal(status, 1);
  assert.match(output, /progress\/features\.json isn't valid JSON/);
});

test("the newest entry in the session log is shown", () => {
  const log = "# Log\n\n## 2026-09-23: the newest\n\n- Did the thing.\n\n## 2026-09-22: older\n\n- Earlier.\n";
  const { output } = check(repo([todo("x")], { "progress/log.md": log }));
  assert.match(output, /Last session \(progress\/log\.md\):\n {2}## 2026-09-23: the newest\n {2}- Did the thing\./);
  assert.doesNotMatch(output, /older/);
});
