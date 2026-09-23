// One command to set up everything: node setup.mjs
//
// Finds Python 3.12 or newer, creates python/.venv, installs the pinned packages from
// python/requirements-lock.txt and the helpdesk itself, then installs the TypeScript packages
// with npm ci. Safe to run again: it reuses the virtual environment and reinstalls the pins,
// which is also how you pick up a changed lock file after pulling a new chapter.
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const WINDOWS = process.platform === "win32";
const VENV_PYTHON = join(ROOT, "python", ".venv", WINDOWS ? "Scripts/python.exe" : "bin/python");

// The longest path the pinned packages install, counted from site-packages (anthropic 1.8.0,
// measured 2026-09-22), and the fixed part of the path from the clone to site-packages.
const LONGEST_INSTALLED_PATH = 133;
const TO_SITE_PACKAGES = "\\python\\.venv\\Lib\\site-packages\\".length;

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
// paths are enabled. Check before installing, so the failure is this message, not pip's.
if (WINDOWS) {
  const total = ROOT.length + TO_SITE_PACKAGES + LONGEST_INSTALLED_PATH;
  if (total > 259 && !longPathsEnabled()) {
    fail(
      `this folder's path is ${ROOT.length} characters long, so the longest installed file would need ` +
        `${total} characters and Windows allows 259. Move the repository to a shorter folder, such as ` +
        "C:\\src\\agent-harness-lab (keep the path under about 90 characters), or enable long paths " +
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
step("Install the pinned Python packages", pip[0], [...pip[1], "-r", "requirements-lock.txt"], { cwd: join(ROOT, "python") });
step("Install the helpdesk package", pip[0], [...pip[1], "-e", ".", "--no-deps"], { cwd: join(ROOT, "python") });
// npm is a .cmd script on Windows, which Node only runs through a shell. The command is fixed text.
step("Install the TypeScript packages", "npm ci", [], { cwd: join(ROOT, "ts"), shell: true });

console.log("\nSetup finished. Next: node check.mjs");
