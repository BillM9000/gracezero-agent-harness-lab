// Proves tools/lockfiles.mjs fails on every gap it claims to find, names the fix, and passes a
// repository where everything matches; and that its hashes command records every file an index
// publishes, from a fake index on 127.0.0.1 (tests never reach another machine).
// Run: node --test tools/lockfiles.test.mjs
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "lockfiles.mjs");
const base = mkdtempSync(join(tmpdir(), "lockfiles-"));
after(() => rmSync(base, { recursive: true, force: true }));

const WINDOWS = process.platform === "win32";
const SITE = WINDOWS ? ["python", ".venv", "Lib", "site-packages"] : ["python", ".venv", "lib", "python3.14", "site-packages"];
const HASH = (c) => c.repeat(64);
const SETUP_OK =
  'step("a", pip[0], [...pip[1], "--require-hashes", "-r", "requirements-lock.txt"]);\n' +
  'step("b", pip[0], [...pip[1], "--no-build-isolation", "-e", ".", "--no-deps"]);\n';
const LOCK_OK =
  "# a comment\n" +
  `alpha==1.0 \\\n    --hash=sha256:${HASH("a")} \\\n    --hash=sha256:${HASH("b")}\n` +
  `Beta_Pkg==2.0 --hash=sha256:${HASH("c")}\n` +
  `winonly==3.0 ; sys_platform == "win32" \\\n    --hash=sha256:${HASH("d")}\n`;
const NPM_OK = {
  lockfileVersion: 3,
  packages: {
    "": { name: "x" },
    "node_modules/left": { version: "1.2.3", resolved: "https://registry.npmjs.org/left/-/left-1.2.3.tgz", integrity: "sha512-AAAA" },
    "node_modules/@x/other-os": {
      version: "0.1.0",
      resolved: "https://registry.npmjs.org/@x/other-os/-/other-os-0.1.0.tgz",
      integrity: "sha512-BBBB",
      optional: true,
    },
  },
};
const INSTALLED_OK = { alpha: "1.0", "beta-pkg": "2.0", pip: "26.0", helpdesk: "0.1.0", ...(WINDOWS ? { winonly: "3.0" } : {}) };

let n = 0;
function repo({ lock = LOCK_OK, setup = SETUP_OK, npm = NPM_OK, installed = INSTALLED_OK, modules = { left: "1.2.3" } } = {}) {
  const root = join(base, `repo-${++n}`);
  mkdirSync(join(root, ...SITE), { recursive: true });
  mkdirSync(join(root, "ts"), { recursive: true });
  writeFileSync(join(root, "python", "requirements-lock.txt"), lock);
  if (setup !== null) writeFileSync(join(root, "setup.mjs"), setup);
  writeFileSync(join(root, "ts", "package-lock.json"), JSON.stringify(npm));
  for (const [name, version] of Object.entries(installed)) {
    const info = join(root, ...SITE, `${name.replaceAll("-", "_")}-${version}.dist-info`);
    mkdirSync(info, { recursive: true });
    writeFileSync(join(info, "METADATA"), `Metadata-Version: 2.4\nName: ${name}\nVersion: ${version}\n`);
  }
  for (const [name, version] of Object.entries(modules)) {
    mkdirSync(join(root, "ts", "node_modules", name), { recursive: true });
    writeFileSync(join(root, "ts", "node_modules", name, "package.json"), JSON.stringify({ name, version }));
  }
  return root;
}

function check(root) {
  const run = spawnSync(process.execPath, [SCRIPT, root], { encoding: "utf8" });
  return { status: run.status, output: run.stdout + run.stderr };
}

test("passes when every pin has a hash, setup requires them, and what's installed matches", () => {
  const { status, output } = check(repo());
  assert.equal(status, 0, output);
  assert.match(output, /3 packages pinned, with 4 hashes; setup\.mjs requires them\./);
  assert.match(output, new RegExp(`the ${WINDOWS ? 3 : 2} packages this platform installs match the lock`));
  assert.match(output, /2 packages, each with a sha512 integrity/);
  assert.match(output, /the 1 installed match the lock; 1 optional ones for other platforms aren't installed/);
});

test("a pin without a hash, or not pinned with ==, fails with the fix", () => {
  const lock = `${LOCK_OK}gamma==4.0\ndelta>=5\n`;
  const { status, output } = check(repo({ lock, installed: { ...INSTALLED_OK, gamma: "4.0", delta: "5" } }));
  assert.equal(status, 1);
  assert.match(output, /gamma: has no hash, so pip can't check what it downloads\. Run node tools\/lockfiles\.mjs hashes\./);
  assert.match(output, /delta: "delta>=5" isn't pinned\. Pin it with ==/);
});

test("a hash that isn't sha256 fails", () => {
  const { status, output } = check(repo({ lock: LOCK_OK.replace(`sha256:${HASH("c")}`, "md5:0123") }));
  assert.equal(status, 1);
  assert.match(output, /Beta_Pkg: --hash=md5:0123 isn't a sha256 digest/);
});

test("a marker it doesn't understand is a problem, not a guess", () => {
  const lock = `${LOCK_OK}odd==1.0 ; python_version < "3.13" --hash=sha256:${HASH("e")}\n`;
  const { status, output } = check(repo({ lock }));
  assert.equal(status, 1);
  assert.match(output, /doesn't understand the marker "python_version < "3\.13""/);
});

test("setup.mjs must require hashes and build without fetching", () => {
  let { status, output } = check(repo({ setup: SETUP_OK.replace('"--require-hashes", ', "") }));
  assert.equal(status, 1);
  assert.match(output, /install the lock with "--require-hashes"/);
  ({ status, output } = check(repo({ setup: SETUP_OK.replace('"--no-build-isolation", ', "") })));
  assert.equal(status, 1);
  assert.match(output, /an isolated build downloads setuptools without a hash/);
});

test("installed Python packages must be the lock's, at its versions, and nothing else", () => {
  const installed = { ...INSTALLED_OK, alpha: "1.1", extra: "9.9" };
  delete installed["beta-pkg"];
  const { status, output } = check(repo({ installed }));
  assert.equal(status, 1);
  assert.match(output, /alpha is 1\.1, and the lock says 1\.0/);
  assert.match(output, /Beta_Pkg==2\.0 is in the lock but isn't installed/);
  assert.match(output, /extra 9\.9 is installed but isn't in the lock, so nothing checked what was downloaded/);
});

test("the platform marker decides whether a package must be installed", () => {
  const installed = { ...INSTALLED_OK };
  delete installed.winonly;
  const { status, output } = check(repo({ installed }));
  if (WINDOWS) {
    assert.equal(status, 1);
    assert.match(output, /winonly==3\.0 is in the lock but isn't installed/);
  } else {
    assert.equal(status, 0, output);
  }
});

test("an npm package without integrity, or from elsewhere, fails", () => {
  const npm = structuredClone(NPM_OK);
  delete npm.packages["node_modules/left"].integrity;
  npm.packages["node_modules/@x/other-os"].resolved = "https://example.com/other-os.tgz";
  const { status, output } = check(repo({ npm }));
  assert.equal(status, 1);
  assert.match(output, /node_modules\/left: no sha512 integrity, so npm ci can't check the download/);
  assert.match(output, /node_modules\/@x\/other-os: resolved from https:\/\/example\.com\/other-os\.tgz/);
});

test("installed npm packages must be at the lock's version, and required ones present", () => {
  let { status, output } = check(repo({ modules: { left: "1.2.4" } }));
  assert.equal(status, 1);
  assert.match(output, /ts\/node_modules\/left: 1\.2\.4 is installed, and the lock says 1\.2\.3/);
  ({ status, output } = check(repo({ modules: {} })));
  assert.equal(status, 1);
  assert.match(output, /ts\/node_modules\/left: required by the lock but not installed/);
});

// The hashes command, against a fake index on 127.0.0.1.
async function withIndex(releases, body) {
  const server = createServer((req, res) => {
    const release = releases[req.url];
    res.writeHead(release ? 200 : 404, { "content-type": "application/json" });
    res.end(JSON.stringify(release ?? {}));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    return await body(`http://127.0.0.1:${server.address().port}/pypi`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

function runHashes(root, index) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [SCRIPT, "hashes", root, "--index", index]);
    let output = "";
    child.stdout.on("data", (d) => (output += d));
    child.stderr.on("data", (d) => (output += d));
    child.on("close", (status) => resolve({ status, output }));
  });
}

test("hashes records every file the index publishes for each pin, sorted, and keeps markers", async () => {
  const root = repo({ lock: "# kept\nalpha==1.0\nwinonly==3.0 ; sys_platform == \"win32\"\n" });
  const releases = {
    "/pypi/alpha/1.0/json": { urls: [{ digests: { sha256: HASH("f") } }, { digests: { sha256: HASH("e") } }] },
    "/pypi/winonly/3.0/json": { urls: [{ digests: { sha256: HASH("9") } }, { digests: { sha256: HASH("9") } }] },
  };
  const { status, output } = await withIndex(releases, (index) => runHashes(root, index));
  assert.equal(status, 0, output);
  assert.match(output, /3 hashes for 2 packages/);
  assert.equal(
    readFileSync(join(root, "python", "requirements-lock.txt"), "utf8"),
    `# kept\nalpha==1.0 \\\n    --hash=sha256:${HASH("e")} \\\n    --hash=sha256:${HASH("f")}\n` +
      `winonly==3.0 ; sys_platform == "win32" \\\n    --hash=sha256:${HASH("9")}\n`,
  );
});

test("hashes stops, naming the pin, when the index doesn't have it", async () => {
  const root = repo({ lock: "alpha==1.0\n" });
  const { status, output } = await withIndex({}, (index) => runHashes(root, index));
  assert.equal(status, 1);
  assert.match(output, /alpha\/1\.0\/json: 404\. Is alpha==1\.0 published there\?/);
});
