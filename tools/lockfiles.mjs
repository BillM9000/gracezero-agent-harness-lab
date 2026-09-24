// The lock files, and what was installed from them (chapter 20): node tools/lockfiles.mjs [root]
//
// A dependency is code you run that someone else wrote, so the lab pins every one and checks each
// download against a hash recorded when it was pinned. This checks, without the network:
//
// 1. python/requirements-lock.txt pins every package with == and gives each at least one
//    --hash=sha256:. pip's hash-checking mode then refuses a download whose hash isn't listed.
// 2. setup.mjs installs the lock with --require-hashes and --only-binary :all:, and builds the
//    helpdesk with --no-build-isolation. An isolated build fetches its build backend (setuptools)
//    without a hash, so the backend is pinned in the lock instead, and the build uses that copy. And
//    with source archives allowed, pip passes over a wheel whose hash is wrong for a source archive
//    whose hash matches, and builds it: code runs, and build tools arrive unchecked.
// 3. python/.venv holds exactly the lock's packages for this platform, at the lock's versions, plus
//    pip, which comes with Python, and the helpdesk itself. pip checks a hash when it downloads a
//    file, not afterwards: a package already installed is left alone. This is the check afterwards.
// 4. ts/package-lock.json gives every package a sha512 integrity and a registry.npmjs.org source.
//    npm ci refuses a download whose integrity differs.
// 5. ts/node_modules holds every package the lock requires, at the lock's version.
//
// node tools/lockfiles.mjs hashes [root] [--index URL] rewrites requirements-lock.txt with the
// sha256 of every file the index publishes for each pinned version, for every platform, read from
// PyPI's JSON API (or the index given). Run it after changing a pin, then node setup.mjs. It
// reaches the network, so its test serves a fake index on 127.0.0.1 instead of reaching PyPI.
//
// Exits 0 when everything matches, 1 with every problem and its fix when anything doesn't.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const command = args[0] === "hashes" ? "hashes" : "check";
const rest = command === "hashes" ? args.slice(1) : args;
const indexAt = rest.indexOf("--index");
const INDEX = indexAt >= 0 ? rest[indexAt + 1] : "https://pypi.org/pypi";
const positional = rest.filter((arg, i) => !(indexAt >= 0 && (i === indexAt || i === indexAt + 1)));
const ROOT = positional[0] ?? join(dirname(fileURLToPath(import.meta.url)), "..");

const LOCK = join(ROOT, "python", "requirements-lock.txt");
const NPM_LOCK = join(ROOT, "ts", "package-lock.json");
const NPM_REGISTRY = "https://registry.npmjs.org/";
// Installed with Python itself, or the lab's own package: not in the lock, and expected.
const PYTHON_EXTRAS = new Set(["pip", "helpdesk"]);

// PEP 503's normal form, so "Pygments", "pydantic_core" and "typing-extensions" compare as pip does.
const normal = (name) => name.toLowerCase().replace(/[-_.]+/g, "-");

// The lock's requirements, one per logical line: continuation backslashes joined, comments dropped.
export function parseLock(text) {
  const logical = text.replace(/\\\r?\n/g, " ").split(/\r?\n/);
  const requirements = [];
  for (const [i, raw] of logical.entries()) {
    const line = raw.replace(/(^|\s)#.*$/, "").trim();
    if (!line) continue;
    const hashes = [...line.matchAll(/--hash=(\w+):([0-9a-f]+)/g)].map((m) => ({ algorithm: m[1], digest: m[2] }));
    const spec = line.replace(/--hash=\S+/g, "").trim();
    const m = /^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(==|>=|<=|~=|!=|>|<)?\s*([^\s;]*)\s*(?:;\s*(.+))?$/.exec(spec);
    requirements.push({
      line: i + 1,
      text: spec,
      name: m ? m[1] : spec,
      operator: m?.[2] ?? "",
      version: m?.[3] ?? "",
      marker: m?.[4]?.trim() ?? "",
      hashes,
      parsed: Boolean(m),
    });
  }
  return requirements;
}

// Whether a requirement applies here. Only the one marker form the lock uses is understood; any
// other is a problem to report, not something to guess at.
function applies(marker, platform = process.platform) {
  if (!marker) return true;
  const m = /^sys_platform\s*(==|!=)\s*["']([^"']+)["']$/.exec(marker);
  if (!m) return undefined;
  return m[1] === "==" ? platform === m[2] : platform !== m[2];
}

function lockProblems(requirements) {
  const problems = [];
  for (const r of requirements) {
    const where = `python/requirements-lock.txt, ${r.name}`;
    if (!r.parsed || r.operator !== "==" || !r.version) {
      problems.push(`${where}: "${r.text}" isn't pinned. Pin it with ==, as pip freeze writes it.`);
    }
    if (r.hashes.length === 0) {
      problems.push(`${where}: has no hash, so pip can't check what it downloads. Run node tools/lockfiles.mjs hashes.`);
    }
    for (const h of r.hashes) {
      if (h.algorithm !== "sha256" || h.digest.length !== 64) {
        problems.push(`${where}: --hash=${h.algorithm}:${h.digest} isn't a sha256 digest. Run node tools/lockfiles.mjs hashes.`);
      }
    }
    if (applies(r.marker) === undefined) {
      problems.push(`${where}: this script doesn't understand the marker "${r.marker}". Add it to applies() in tools/lockfiles.mjs.`);
    }
  }
  return problems;
}

function setupProblems() {
  const path = join(ROOT, "setup.mjs");
  if (!existsSync(path)) return ["setup.mjs: not found. The lock is only as good as the command that installs from it."];
  const lines = readFileSync(path, "utf8").split(/\r?\n/);
  const problems = [];
  const lockLine = lines.find((line) => line.includes('"requirements-lock.txt"'));
  if (!lockLine?.includes('"--require-hashes"')) {
    problems.push('setup.mjs: install the lock with "--require-hashes", so a package without a hash is refused, not installed.');
  }
  if (!lockLine?.includes('"--only-binary", ":all:"')) {
    problems.push(
      'setup.mjs: install the lock with "--only-binary", ":all:": otherwise a wheel whose hash is wrong is passed over ' +
        "for a source archive, and building that runs code and fetches build tools without a hash.",
    );
  }
  const buildLine = lines.find((line) => line.includes('"-e", "."'));
  if (!buildLine?.includes('"--no-build-isolation"')) {
    problems.push('setup.mjs: build the helpdesk with "--no-build-isolation": an isolated build downloads setuptools without a hash.');
  }
  return problems;
}

function sitePackagesDir() {
  const venv = join(ROOT, "python", ".venv");
  if (process.platform === "win32") return join(venv, "Lib", "site-packages");
  const lib = join(venv, "lib");
  const version = existsSync(lib) ? readdirSync(lib).find((name) => name.startsWith("python3")) : undefined;
  return join(lib, version ?? "python3", "site-packages");
}

// Every distribution in site-packages, from its dist-info METADATA: name and version.
function installedPython() {
  const dir = sitePackagesDir();
  if (!existsSync(dir)) return null;
  const found = new Map();
  for (const entry of readdirSync(dir)) {
    if (!entry.endsWith(".dist-info")) continue;
    const metadata = join(dir, entry, "METADATA");
    if (!existsSync(metadata)) continue;
    const text = readFileSync(metadata, "utf8");
    const name = /^Name:\s*(.+)$/m.exec(text)?.[1].trim();
    const version = /^Version:\s*(.+)$/m.exec(text)?.[1].trim();
    if (name) found.set(normal(name), { name, version });
  }
  return found;
}

function installedPythonProblems(requirements) {
  const installed = installedPython();
  if (installed === null) return { problems: ["python/.venv: no installed packages. Run node setup.mjs first."], count: 0 };
  const problems = [];
  const wanted = new Map(requirements.filter((r) => applies(r.marker)).map((r) => [normal(r.name), r]));
  for (const [key, r] of wanted) {
    const got = installed.get(key);
    if (!got) problems.push(`python/.venv: ${r.name}==${r.version} is in the lock but isn't installed. Run node setup.mjs.`);
    else if (got.version !== r.version) {
      problems.push(`python/.venv: ${r.name} is ${got.version}, and the lock says ${r.version}. Run node setup.mjs.`);
    }
  }
  for (const [key, got] of installed) {
    if (!wanted.has(key) && !PYTHON_EXTRAS.has(key)) {
      problems.push(
        `python/.venv: ${got.name} ${got.version} is installed but isn't in the lock, so nothing checked what was ` +
          "downloaded. Add it with its hashes, or uninstall it.",
      );
    }
  }
  return { problems, count: wanted.size };
}

function npmProblems() {
  if (!existsSync(NPM_LOCK)) return { problems: ["ts/package-lock.json: not found. Run npm install in ts once, and commit it."], total: 0 };
  const lock = JSON.parse(readFileSync(NPM_LOCK, "utf8"));
  const problems = [];
  let installed = 0;
  let skipped = 0;
  const entries = Object.entries(lock.packages ?? {}).filter(([key]) => key !== "");
  for (const [key, entry] of entries) {
    const where = `ts/package-lock.json, ${key}`;
    if (entry.link) {
      problems.push(`${where}: a link, which has no integrity to check. Install it from the registry.`);
      continue;
    }
    if (!/^sha512-[A-Za-z0-9+/=]+$/.test(entry.integrity ?? "")) {
      problems.push(`${where}: no sha512 integrity, so npm ci can't check the download. Run npm install in ts to record it.`);
    }
    if (!(entry.resolved ?? "").startsWith(NPM_REGISTRY)) {
      problems.push(`${where}: resolved from ${entry.resolved ?? "nowhere"}, not ${NPM_REGISTRY}. Install it from the registry.`);
    }
    const manifest = join(ROOT, "ts", key, "package.json");
    if (!existsSync(manifest)) {
      if (entry.optional) skipped++;
      else problems.push(`ts/${key}: required by the lock but not installed. Run npm ci in ts.`);
      continue;
    }
    installed++;
    const version = JSON.parse(readFileSync(manifest, "utf8")).version;
    if (version !== entry.version) {
      problems.push(`ts/${key}: ${version} is installed, and the lock says ${entry.version}. Run npm ci in ts.`);
    }
  }
  return { problems, total: entries.length, installed, skipped };
}

async function writeHashes() {
  const text = readFileSync(LOCK, "utf8");
  const header = text.split(/\r?\n/).filter((line) => line.startsWith("#"));
  const out = [...header];
  let files = 0;
  for (const r of parseLock(text)) {
    if (!r.parsed || r.operator !== "==") {
      console.error(`${r.text}: pin it with == before hashing it.`);
      process.exit(1);
    }
    const url = `${INDEX}/${r.name}/${r.version}/json`;
    const response = await fetch(url);
    if (!response.ok) {
      console.error(`${url}: ${response.status}. Is ${r.name}==${r.version} published there?`);
      process.exit(1);
    }
    const release = await response.json();
    const digests = [...new Set((release.urls ?? []).map((file) => file.digests?.sha256).filter(Boolean))].sort();
    if (digests.length === 0) {
      console.error(`${url}: lists no files for ${r.name}==${r.version}.`);
      process.exit(1);
    }
    files += digests.length;
    const spec = r.marker ? `${r.name}==${r.version} ; ${r.marker}` : `${r.name}==${r.version}`;
    out.push(`${spec} \\`, ...digests.map((d, i) => `    --hash=sha256:${d}${i < digests.length - 1 ? " \\" : ""}`));
  }
  writeFileSync(LOCK, `${out.join("\n")}\n`);
  console.log(`python/requirements-lock.txt: ${files} hashes for ${parseLock(readFileSync(LOCK, "utf8")).length} packages, from ${INDEX}.`);
}

if (command === "hashes") {
  await writeHashes();
} else {
  if (!existsSync(LOCK)) {
    console.error(`No python/requirements-lock.txt in ${ROOT}.`);
    process.exit(1);
  }
  const requirements = parseLock(readFileSync(LOCK, "utf8"));
  const python = installedPythonProblems(requirements);
  const npm = npmProblems();
  const problems = [...lockProblems(requirements), ...setupProblems(), ...python.problems, ...npm.problems];
  if (problems.length) {
    console.error(problems.join("\n"));
    console.error(`\nlockfiles: ${problems.length} problem(s).`);
    process.exit(1);
  }
  const hashes = requirements.reduce((n, r) => n + r.hashes.length, 0);
  console.log(`python/requirements-lock.txt: ${requirements.length} packages pinned, with ${hashes} hashes; setup.mjs requires them.`);
  console.log(`python/.venv: the ${python.count} packages this platform installs match the lock.`);
  console.log(`ts/package-lock.json: ${npm.total} packages, each with a sha512 integrity from ${NPM_REGISTRY}.`);
  console.log(`ts/node_modules: the ${npm.installed} installed match the lock; ${npm.skipped} optional ones for other platforms aren't installed.`);
}
