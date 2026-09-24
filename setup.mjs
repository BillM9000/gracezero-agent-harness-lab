// One command to set up everything: node setup.mjs
//
// Finds Python 3.12 or newer, creates python/.venv, installs the pinned packages from
// python/requirements-lock.txt and the helpdesk itself, then installs the TypeScript packages
// with npm ci. Safe to run again: it reuses the virtual environment and reinstalls the pins,
// which is also how you pick up a changed lock file after pulling a new chapter.
//
// Every download is checked against a hash recorded in a lock file (chapter 20): pip's
// --require-hashes refuses a Python package whose hash isn't in requirements-lock.txt, npm ci one
// whose integrity differs from package-lock.json, and the helpdesk is built with the setuptools the
// lock installed (--no-build-isolation), not one fetched unchecked. tools/lockfiles.mjs checks all this.
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const WINDOWS = process.platform === "win32";
const VENV_PYTHON = join(ROOT, "python", ".venv", WINDOWS ? "Scripts/python.exe" : "bin/python");

// The longest file the pinned packages install, counted from site-packages: a module in
// anthropic 1.8.0, measured 2026-09-22. Compiled bytecode in __pycache__ runs longer, but pip
// skips a compiled file it can't write and Python runs without it, so it doesn't count here.
// tools/install-paths.mjs measures the installed packages again on every check, so this number
// can't quietly go stale when a package is added.
const LONGEST_INSTALLED_FILE = 108;
// The fixed part of the path from the clone to site-packages, and Windows' limit on a whole path.
const TO_SITE_PACKAGES = "\\python\\.venv\\Lib\\site-packages\\".length;
const WINDOWS_PATH_LIMIT = 259;

function fail(message) {
  console.error(`\nSetup stopped: ${message}`);
  process.exit(1);
}

function step(label, command, args, options = {}) {
  console.log(`\n== ${label}`);
  const run = spawnSync(command, args, { stdio: "inherit", ...options });
  if (run.error) fail(`could not run ${command}: ${run.error.message}`);
  if (run.status !== 0) fail(`"${label}" exited with code ${run.status}. Read the output above for the cause.`);
}

function longPathsEnabled() {
  try {
    const out = execFileSync("reg", ["query", "HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem", "/v", "LongPathsEnabled"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    return /LongPathsEnabled\s+REG_DWORD\s+0x1\b/.test(out);
  } catch {
    return false;
  }
}

// Windows limits a whole path to 260 characters (259 plus a terminating null) unless long
// paths are enabled. pip writes each file straight to its final path, so in a folder that is too
// deep it stops part way through with "No such file or directory". Check before installing, so
// the failure is this message instead.
if (WINDOWS) {
  const longestFolder = WINDOWS_PATH_LIMIT - TO_SITE_PACKAGES - LONGEST_INSTALLED_FILE;
  if (ROOT.length > longestFolder && !longPathsEnabled()) {
    fail(
      `this folder's path is ${ROOT.length} characters long, and on Windows it can be at most ${longestFolder}: ` +
        `the longest file the Python packages install would need a path of ` +
        `${ROOT.length + TO_SITE_PACKAGES + LONGEST_INSTALLED_FILE} characters, and Windows allows ${WINDOWS_PATH_LIMIT}. ` +
        "Move the repository to a shorter folder, such as C:\\src\\agent-harness-lab, or enable long paths " +
        "as Microsoft's page \"Maximum Path Length Limitation\" describes, then run setup again.",
    );
  }
}

function findPython() {
  const candidates = process.env.HELPDESK_PYTHON
    ? [[process.env.HELPDESK_PYTHON, []]]
    : WINDOWS
      ? [["py", ["-3"]], ["python", []]]
      : [["python3", []], ["python", []]];
  for (const [command, prefix] of candidates) {
    try {
      const version = execFileSync(command, [...prefix, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      }).trim();
      const [major, minor] = version.split(".").map(Number);
      if (major === 3 && minor >= 12) return { command, prefix, version };
    } catch {
      // Not installed under that name; try the next one.
    }
  }
  return null;
}

if (!existsSync(VENV_PYTHON)) {
  const python = findPython();
  if (!python) {
    fail("no Python 3.12 or newer was found. Install one from python.org, or set HELPDESK_PYTHON to its path.");
  }
  step(`Create python/.venv with Python ${python.version}`, python.command, [...python.prefix, "-m", "venv", join(ROOT, "python", ".venv")]);
} else {
  console.log("\n== python/.venv already exists; reusing it");
}

const pip = [VENV_PYTHON, ["-m", "pip", "install", "--disable-pip-version-check", "-q"]];
step("Install the pinned Python packages", pip[0], [...pip[1], "--require-hashes", "-r", "requirements-lock.txt"], { cwd: join(ROOT, "python") });
step("Install the helpdesk package", pip[0], [...pip[1], "--no-build-isolation", "-e", ".", "--no-deps"], { cwd: join(ROOT, "python") });
// npm is a .cmd script on Windows, which Node only runs through a shell. The command is fixed text.
step("Install the TypeScript packages", "npm ci", [], { cwd: join(ROOT, "ts"), shell: true });

console.log("\nSetup finished. Next: node check.mjs");
