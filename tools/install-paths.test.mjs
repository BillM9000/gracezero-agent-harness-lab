// Proves the path-limit check fails when an installed file outgrows setup.mjs's number, ignores
// compiled bytecode, and refuses to pass when it can't read the number or find the packages.
// Run: node --test tools/install-paths.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPT = join(HERE, "install-paths.mjs");
const base = mkdtempSync(join(tmpdir(), "install-paths-"));
after(() => rmSync(base, { recursive: true, force: true }));

const SITE_PACKAGES =
  process.platform === "win32" ? ["python", ".venv", "Lib", "site-packages"] : ["python", ".venv", "lib", "python3.14", "site-packages"];

let n = 0;
// A fake repository: a setup.mjs (or the text given) and a site-packages folder holding the files given.
function repo({ limit = 20, setup, files = {} }) {
  const root = join(base, `repo-${++n}`);
  mkdirSync(root, { recursive: true });
  writeFileSync(join(root, "setup.mjs"), setup ?? `const LONGEST_INSTALLED_FILE = ${limit};\n`);
  for (const [path, content] of Object.entries(files)) {
    const full = join(root, ...SITE_PACKAGES, ...path.split("/"));
    mkdirSync(dirname(full), { recursive: true });
    writeFileSync(full, content);
  }
  return root;
}

function check(root) {
  const run = spawnSync(process.execPath, [SCRIPT, root], { encoding: "utf8" });
  return { status: run.status, output: run.stdout + run.stderr };
}

// "pkg/" plus a name of this many characters, so the path from site-packages has the length given.
const fileOfLength = (length) => `pkg/${"m".repeat(length - "pkg/".length - ".py".length)}.py`;

test("passes when every installed file fits setup.mjs's number", () => {
  const { status, output } = check(repo({ limit: 20, files: { [fileOfLength(20)]: "", [fileOfLength(12)]: "" } }));
  assert.equal(status, 0, output);
  assert.match(output, /The longest installed file is 20 characters, and setup\.mjs allows for 20/);
});

test("fails, naming the file and the fix, when a file is longer than setup.mjs allows for", () => {
  const { status, output } = check(repo({ limit: 20, files: { [fileOfLength(21)]: "" } }));
  assert.equal(status, 1);
  assert.match(output, /install a file 21 characters long/);
  assert.match(output, /pkg[\\/]m+\.py/);
  assert.match(output, /Change LONGEST_INSTALLED_FILE in setup\.mjs to 21\./);
});

test("ignores compiled bytecode, which pip skips when its path is too long", () => {
  const cached = "pkg/__pycache__/a_module_with_a_long_name.cpython-314.pyc";
  const { status, output } = check(repo({ limit: 20, files: { [fileOfLength(20)]: "", [cached]: "" } }));
  assert.equal(status, 0, output);
});

test("refuses to pass when setup.mjs has no number to check", () => {
  const { status, output } = check(repo({ setup: "const SOMETHING_ELSE = 108;\n", files: { [fileOfLength(10)]: "" } }));
  assert.equal(status, 1);
  assert.match(output, /Couldn't find a line like 'const LONGEST_INSTALLED_FILE = 108;'/);
});

test("refuses to pass when nothing is installed yet", () => {
  const { status, output } = check(repo({ limit: 20 }));
  assert.equal(status, 1);
  assert.match(output, /Run node setup\.mjs first/);
});

test("can read the number in the real setup.mjs", () => {
  const root = repo({ files: { [fileOfLength(10)]: "" } });
  copyFileSync(join(HERE, "..", "setup.mjs"), join(root, "setup.mjs"));
  const { status, output } = check(root);
  assert.equal(status, 0, output);
  assert.match(output, /setup\.mjs allows for \d+/);
});
