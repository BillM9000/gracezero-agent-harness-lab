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

// A review (2026-09-26) found done items passing on proofs no test runner collects: a fixture in
// conftest.py, a function in the app, and a title that appears only in a string.
const NOT_TESTS = {
  "python/tests/conftest.py": "import pytest\n\n@pytest.fixture\ndef conn():\n    return None\n",
  "python/src/app/triage.py": "def main():\n    return 0\n\ndef test_main():\n    assert main() == 0\n",
  "python/tests/test_helpers.py":
    'def helper():\n    return 1\n\ndef test_real():\n    assert helper() == 1\n\n' +
    '"""\ndef test_in_a_docstring():\n    pass\n"""\n# def test_in_a_comment():\n\nclass TestGroup:\n    def test_a_method(self):\n        pass\n',
  "ts/src/client.ts": 'export const note = "test(\\"the client retries\\")";\ntest("the client retries", () => {});\n',
  "tools/b.test.mjs":
    'const planted = \'test("only in a string", () => {})\';\n// test("only in a comment", () => {});\n' +
    '/* it("only in a block comment") */\nconst re = /it("in a regular expression")/;\n' +
    'test("a real one", () => { const s = "}"; });\n',
};

test("a proof that no test runner collects fails: a fixture, the app's code, a helper, a string", () => {
  const items = [
    done("fixture", "python/tests/conftest.py::conn"),
    done("app-code", "python/src/app/triage.py::test_main"),
    done("helper", "python/tests/test_helpers.py::helper"),
    done("docstring", "python/tests/test_helpers.py::test_in_a_docstring"),
    done("comment", "python/tests/test_helpers.py::test_in_a_comment"),
    done("method", "python/tests/test_helpers.py::test_a_method"),
    done("ts-source", "ts/src/client.ts::the client retries"),
    done("js-string", "tools/b.test.mjs::only in a string"),
    done("js-comment", "tools/b.test.mjs::only in a comment"),
    done("js-block", "tools/b.test.mjs::only in a block comment"),
    done("js-regex", "tools/b.test.mjs::in a regular expression"),
  ];
  const { status, output } = check(repo(items, NOT_TESTS));
  assert.equal(status, 1);
  assert.match(output, /fixture: is marked done, but its proof file, python\/tests\/conftest\.py, isn't a file pytest collects: name a test_\*\.py file\./);
  assert.match(output, /app-code: is marked done, but its proof file, python\/src\/app\/triage\.py, isn't a file pytest collects/);
  assert.match(output, /helper: is marked done, but its proof names helper, and pytest runs only functions whose names start with test\./);
  for (const id of ["docstring", "comment", "method"]) assert.match(output, new RegExp(`- ${id}: is marked done, but its proof names test_\\w+, which isn't a test in python/tests/test_helpers\\.py\\.`));
  assert.match(output, /ts-source: is marked done, but its proof file, ts\/src\/client\.ts, isn't a test file: name a \*\.test\.\* or \*\.spec\.\* file/);
  for (const id of ["js-string", "js-comment", "js-block", "js-regex"]) assert.match(output, new RegExp(`- ${id}: is marked done, but its proof names .*, which isn't a test in tools/b\\.test\\.mjs\\.`));
  assert.match(output, /11 problems:/);
});

test("real tests beside the decoys still pass, and pytest's testpaths decide where a Python test may be", () => {
  const good = [done("python", "python/tests/test_helpers.py::test_real"), done("script", "tools/b.test.mjs::a real one")];
  const passing = check(repo(good, NOT_TESTS));
  assert.equal(passing.status, 0, passing.output);
  const pyproject = { "python/pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n\n[tool.ruff]\nline-length = 110\n' };
  const outside = check(repo([done("elsewhere", "python/other/test_x.py::test_x")], { ...pyproject, "python/other/test_x.py": "def test_x():\n    pass\n" }));
  assert.equal(outside.status, 1);
  assert.match(outside.output, /elsewhere: is marked done, but its proof file, python\/other\/test_x\.py, isn't a file pytest collects: name a test_\*\.py file under python\/tests\//);
  assert.equal(check(repo([done("inside", "python/tests/test_app.py::test_it_works")], pyproject)).status, 0);
});
