// Checks that what the repository's documentation claims is still true (chapter 8).
//
// Two kinds of claim can be checked by a script, so both are:
//   - Paths. Every path in backticks that starts at the repository's root, and every relative
//     link target, must exist.
//   - Numbers. A number right after a <!-- claim: NAME --> marker must equal what the counter
//     called NAME measures in the repository now. The number is read from the document itself,
//     not from a separate list of expected values, so the document can't drift from the check.
// Everything else in the prose is not checked, and the report says so.
//
// Only documents that describe the repository as it is now are read. CHANGELOG.md records what
// was true at the time, so it's left out on purpose.
//
// Usage: node tools/doc-claims.mjs [path]   (default: the current folder)
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join, posix } from "node:path";

import { listFiles } from "./harness-inventory.mjs";

const DOCS = ["README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "SECURITY.md", "templates/README.md"];
// Folders the lab's setup creates; git ignores them, so paths inside them can't be checked.
const CREATED_BY_SETUP = ["python/.venv", "ts/node_modules"];

// What each claim name measures, and how.
const COUNTERS = {
  checks: {
    what: "checks that node check.mjs runs",
    count: (root) => {
      const run = spawnSync(process.execPath, ["check.mjs", "--list"], { cwd: root, encoding: "utf8" });
      if (run.status !== 0) throw new Error(`node check.mjs --list failed: ${run.stderr.trim()}`);
      return run.stdout.split("\n").filter((line) => line.trim() !== "").length;
    },
  },
  "import-contracts": {
    what: "import-linter contracts in python/pyproject.toml",
    count: (root) => (readFileSync(join(root, "python", "pyproject.toml"), "utf8").match(/^\[\[tool\.importlinter\.contracts\]\]/gm) ?? []).length,
  },
  postings: {
    what: "postings in the chapter 1 sample",
    count: (root) => JSON.parse(readFileSync(join(root, "postings", "sample-2026-09-22.json"), "utf8")).postings.length,
  },
};

const root = process.argv[2] ?? ".";
const tracked = listFiles(root);
const topLevel = new Set(tracked.map((file) => file.split("/")[0]));
const exists = (path) => tracked.includes(path) || tracked.some((file) => file.startsWith(`${path}/`));
const createdBySetup = (path) => CREATED_BY_SETUP.some((folder) => path === folder || path.startsWith(`${folder}/`));
// Only tracked files count: a file on one person's disk isn't in anyone else's copy.
const missing = (path, what) =>
  existsSync(join(root, path))
    ? `${what} is on disk but not tracked by git, so no one else has it. Add it with git add, or fix the document.`
    : `${what} doesn't exist. Fix the path in the document, or restore the file.`;

const problems = [];
const numbers = [];
let pathsChecked = 0;
const docs = DOCS.filter((doc) => tracked.includes(doc));

for (const doc of docs) {
  const lines = readFileSync(join(root, doc), "utf8").split(/\r?\n/);
  let fence = false;
  lines.forEach((line, i) => {
    const at = `${doc}:${i + 1}`;
    if (/^ {0,3}(```|~~~)/.test(line)) {
      fence = !fence;
      return;
    }
    if (fence) return;

    // Paths in backticks that start at the root, on their own or inside a command such as
    // `node tools/x.mjs`: no placeholders, and a first part that is a top-level file or folder.
    for (const [, span] of line.matchAll(/`([^`]+)`/g)) {
      for (const token of span.split(/\s+/)) {
        const path = token.replace(/\/$/, "");
        if (!path.includes("/") || /[<>*{}[\]]|\.\.\./.test(path) || !topLevel.has(path.split("/")[0]) || createdBySetup(path)) continue;
        pathsChecked++;
        if (!exists(path)) problems.push(`${at}: ${missing(path, `\`${token}\``)}`);
      }
    }

    // Relative link targets, resolved from the document's folder.
    for (const [, target] of line.matchAll(/\]\(([^)\s#]+)(?:#[^)]*)?\)/g)) {
      if (/^[a-z][a-z0-9+.-]*:/i.test(target)) continue; // a URL, not a path
      pathsChecked++;
      const path = posix.normalize(posix.join(posix.dirname(doc), target)).replace(/\/$/, "");
      if (!exists(path)) problems.push(`${at}: the link to ${target} leads nowhere. ${missing(path, "The target")}`);
    }

    // Numbers that a marker says a counter can check. A marker inside backticks is an example of
    // the syntax, not a claim.
    for (const m of line.replace(/`[^`]*`/g, "").matchAll(/<!--\s*claim:\s*([\w-]+)\s*-->\s*(\d[\d,]*)?/g)) {
      const [, name, written] = m;
      const counter = COUNTERS[name];
      if (!counter) {
        problems.push(`${at}: <!-- claim: ${name} --> names no counter. Known counters: ${Object.keys(COUNTERS).join(", ")}.`);
        continue;
      }
      if (written === undefined) {
        problems.push(`${at}: <!-- claim: ${name} --> must be followed straight away by the number it claims.`);
        continue;
      }
      let live;
      try {
        live = counter.count(root);
      } catch (err) {
        problems.push(`${at}: couldn't count ${counter.what}: ${err.message}`);
        continue;
      }
      const claimed = Number(written.replaceAll(",", ""));
      numbers.push({ at, name, claimed, live });
      if (claimed !== live) {
        problems.push(`${at}: says ${claimed} ${counter.what}, but there are ${live}. Update the document, or the code if the document is right.`);
      }
    }
  });
}

console.log(`Documentation claims: ${root}\n`);
console.log(`Paths: ${pathsChecked} checked in ${docs.join(", ") || "no documents"}.`);
if (numbers.length > 0) {
  console.log("Numbers:");
  const width = Math.max(...numbers.map((n) => n.at.length));
  for (const n of numbers) console.log(`  ${n.at.padEnd(width)}  ${n.name.padEnd(16)}  says ${n.claimed}, counted ${n.live}`);
} else {
  console.log("Numbers: none marked.");
}
console.log("");
if (problems.length === 0) {
  console.log("No problems found. Only paths and marked numbers are checked; the rest of the prose isn't.");
  process.exit(0);
}
console.log(`${problems.length} problem${problems.length === 1 ? "" : "s"}:`);
for (const problem of problems) console.log(`- ${problem}`);
process.exit(1);
