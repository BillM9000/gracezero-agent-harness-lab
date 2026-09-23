// Checks that setup.mjs's Windows path limit still fits the installed Python packages.
//
// On Windows, setup.mjs stops before installing anything when the clone's folder is too deep for
// the longest file pip will write. It knows that length as LONGEST_INSTALLED_FILE, a number
// measured from the packages pinned at the time. This script measures the installed packages
// again and fails if any file is now longer, so adding a package can't quietly make setup's
// check wrong. Compiled bytecode in __pycache__ is left out: pip skips a compiled file whose path
// is too long, and Python runs without it.
//
// Run after node setup.mjs:  node tools/install-paths.mjs [repository-root]
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = process.argv[2] ?? join(dirname(fileURLToPath(import.meta.url)), "..");

function fail(message) {
  console.error(message);
  process.exit(1);
}

// Where the virtual environment keeps its packages: Lib\site-packages on Windows,
// lib/python3.N/site-packages elsewhere.
function sitePackagesDir() {
  const venv = join(root, "python", ".venv");
  if (process.platform === "win32") return join(venv, "Lib", "site-packages");
  const lib = join(venv, "lib");
  const version = existsSync(lib) ? readdirSync(lib).find((name) => name.startsWith("python3")) : undefined;
  return join(lib, version ?? "python3", "site-packages");
}

// The longest file under site-packages, outside __pycache__, as a path relative to site-packages.
function longestInstalledFile(sitePackages) {
  let longest = { length: 0, path: "" };
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "__pycache__") continue;
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else {
        const path = relative(sitePackages, full);
        if (path.length > longest.length) longest = { length: path.length, path };
      }
    }
  };
  walk(sitePackages);
  return longest;
}

const setupPath = join(root, "setup.mjs");
if (!existsSync(setupPath)) fail(`No setup.mjs in ${root}.`);
const match = /^const LONGEST_INSTALLED_FILE = (\d+);$/m.exec(readFileSync(setupPath, "utf8"));
if (!match) {
  fail("Couldn't find a line like 'const LONGEST_INSTALLED_FILE = 108;' in setup.mjs. Put it back, or change this script to match.");
}
const limit = Number(match[1]);

const sitePackages = sitePackagesDir();
if (!existsSync(sitePackages)) fail(`No installed packages at ${sitePackages}. Run node setup.mjs first.`);

const longest = longestInstalledFile(sitePackages);
if (longest.length > limit) {
  fail(
    `The Python packages now install a file ${longest.length} characters long, counted from site-packages:\n` +
      `  ${longest.path}\n` +
      `setup.mjs allows for ${limit}, so on Windows its path check would let through a folder too deep for this file, ` +
      `and pip would fail part way through the install. Change LONGEST_INSTALLED_FILE in setup.mjs to ${longest.length}.`,
  );
}
console.log(`The longest installed file is ${longest.length} characters, and setup.mjs allows for ${limit}: ${longest.path}`);
