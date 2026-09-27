// Shows where the lab's work stands, and checks that the work list can be trusted (chapter 10).
//
// progress/features.json lists the work, each item todo, in-progress or done. The list is only
// useful to the next session if "done" means something, so this fails when:
//   - an item marked done names no proof, or names a test that doesn't exist, or something that
//     isn't a test the runners collect: a Python proof must be a function named test* at the top of
//     a test_*.py file, under pytest's testpaths when python/pyproject.toml sets them; a JavaScript
//     or TypeScript proof must be a test(...) or it(...) call with that title in a *.test.* or
//     *.spec.* file, found in the code rather than in a comment or a string;
//   - more than one item is in progress (one unit of work at a time);
//   - an item is malformed, or two items share an id.
// It checks that each proof test exists; node check.mjs runs the tests themselves. The scan for a
// test is a simple one (strings, comments and JavaScript's regular expressions skipped by their
// quotes and slashes), not a parser, so a proof it accepts is still worth reading.
//
// It also prints the next item to work on and the newest entry in progress/log.md: what a session
// starting cold needs first.
//
// Usage: node tools/progress.mjs [path]
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { listFiles } from "./harness-inventory.mjs";

const LIST = "progress/features.json";
const LOG = "progress/log.md";
const STATUSES = ["todo", "in-progress", "done"];

const root = process.argv[2] ?? ".";
const problems = [];

function finish() {
  if (problems.length === 0) {
    console.log("No problems found.");
    process.exit(0);
  }
  console.log(`${problems.length} problem${problems.length === 1 ? "" : "s"}:`);
  for (const problem of problems) console.log(`- ${problem}`);
  process.exit(1);
}

console.log(`Work list: ${LIST}\n`);
if (!existsSync(join(root, LIST))) {
  problems.push(`${LIST} doesn't exist. Create it with a "features" list.`);
  finish();
}
let list;
try {
  list = JSON.parse(readFileSync(join(root, LIST), "utf8"));
} catch (err) {
  problems.push(`${LIST} isn't valid JSON: ${err.message}`);
  finish();
}
const features = Array.isArray(list?.features) ? list.features : [];
if (!Array.isArray(list?.features)) problems.push(`${LIST} needs a "features" list.`);

const tracked = new Set(listFiles(root));
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Where pytest looks for tests, from python/pyproject.toml's [tool.pytest.ini_options] testpaths,
// as folders from the root; none when the file or the setting isn't there.
function pytestPaths() {
  const path = join(root, "python", "pyproject.toml");
  if (!existsSync(path)) return [];
  const section = /^\[tool\.pytest\.ini_options\]\s*$([\s\S]*?)(?=^\[|(?![\s\S]))/m.exec(readFileSync(path, "utf8"));
  const paths = section && /^testpaths\s*=\s*\[([^\]]*)\]/m.exec(section[1]);
  return paths ? [...paths[1].matchAll(/["']([^"']+)["']/g)].map((m) => `python/${m[1].replace(/\/+$/, "")}/`) : [];
}

// The source with every string and comment blanked out (newlines kept, so lines and columns stay
// where they were), and the strings themselves with where they start. JavaScript's regular
// expression literals are blanked too, where a slash follows something that can't end a value.
function scan(text, python) {
  const code = [...text];
  const strings = [];
  const blank = (from, to) => {
    for (let k = from; k < to; k++) if (code[k] !== "\n") code[k] = " ";
  };
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (python ? c === "#" : text.startsWith("//", i)) {
      const end = text.indexOf("\n", i);
      blank(i, end < 0 ? text.length : end);
      i = end < 0 ? text.length : end;
    } else if (!python && text.startsWith("/*", i)) {
      const end = text.indexOf("*/", i + 2);
      blank(i, end < 0 ? text.length : end + 2);
      i = end < 0 ? text.length : end + 2;
    } else if (c === '"' || c === "'" || (!python && c === "`")) {
      const quote = python && text.startsWith(c.repeat(3), i) ? c.repeat(3) : c;
      let j = i + quote.length;
      let value = "";
      while (j < text.length && !text.startsWith(quote, j)) {
        if (text[j] === "\\") {
          value += text[j + 1] ?? "";
          j += 2;
        } else {
          value += text[j];
          j += 1;
        }
      }
      strings.push({ start: i, value });
      const end = Math.min(text.length, j + quote.length);
      blank(i, end);
      i = end;
    } else if (!python && c === "/" && /(^|[(,=:[!&|?{};+\-*%<>~^]|\breturn|\btypeof)\s*$/.test(text.slice(Math.max(0, i - 12), i))) {
      let j = i + 1;
      let inClass = false;
      while (j < text.length && text[j] !== "\n" && (inClass || text[j] !== "/")) {
        if (text[j] === "\\") j += 1;
        else if (text[j] === "[") inClass = true;
        else if (text[j] === "]") inClass = false;
        j += 1;
      }
      blank(i, j + 1);
      i = j + 1;
    } else {
      i += 1;
    }
  }
  return { code: code.join(""), strings };
}

const PYTHON_TEST_FILE = /(^|\/)test_[^/]*\.py$/;
const SCRIPT_TEST_FILE = /\.(test|spec)\.[cm]?[jt]s$/;

// Does the proof name a test the runners collect? A Python test is a function named test* defined
// at the top of a test_*.py file (under pytest's testpaths, when set); a JavaScript or TypeScript
// test is a test(...) or it(...) call with that title in a *.test.* or *.spec.* file. A def or a
// call inside a string or a comment doesn't count.
function proofProblem(proof) {
  const match = /^([^:]+)::(.+)$/.exec(proof);
  if (!match) return `"${proof}" isn't a proof. Write it as <test file>::<test name>.`;
  const [, file, name] = match;
  if (!tracked.has(file)) return `its proof file, ${file}, isn't in the repository.`;
  const text = readFileSync(join(root, file), "utf8");
  if (file.endsWith(".py")) {
    const under = pytestPaths();
    if (!PYTHON_TEST_FILE.test(file) || (under.length && !under.some((folder) => file.startsWith(folder)))) {
      const where = under.length ? ` under ${under.join(" or ")}` : "";
      return `its proof file, ${file}, isn't a file pytest collects: name a test_*.py file${where}.`;
    }
    if (!/^test\w*$/.test(name)) return `its proof names ${name}, and pytest runs only functions whose names start with test.`;
    const { code } = scan(text, true);
    const found = new RegExp(`^(async\\s+)?def ${escape(name)}\\(`, "m").test(code);
    return found ? null : `its proof names ${name}, which isn't a test in ${file}.`;
  }
  if (!SCRIPT_TEST_FILE.test(file)) {
    return `its proof file, ${file}, isn't a test file: name a *.test.* or *.spec.* file the test runner reads.`;
  }
  const { code, strings } = scan(text, false);
  const found = strings.some((s) => s.value === name && /\b(test|it)\s*\(\s*$/.test(code.slice(Math.max(0, s.start - 40), s.start)));
  return found ? null : `its proof names ${name}, which isn't a test in ${file}.`;
}

const seen = new Set();
features.forEach((item, i) => {
  const label = typeof item?.id === "string" && item.id !== "" ? item.id : `item ${i + 1}`;
  if (typeof item?.id !== "string" || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(item.id)) {
    problems.push(`${label}: needs an id in lowercase words joined by hyphens.`);
  } else if (seen.has(item.id)) {
    problems.push(`${label}: another item has the same id.`);
  }
  seen.add(item?.id);
  if (typeof item?.description !== "string" || item.description.trim() === "") problems.push(`${label}: needs a description.`);
  if (!STATUSES.includes(item?.status)) {
    problems.push(`${label}: its status is ${JSON.stringify(item?.status)}; use one of ${STATUSES.join(", ")}.`);
  } else if (item.status === "done") {
    if (typeof item.proof !== "string" || item.proof === "") {
      problems.push(`${label}: is marked done but names no proof. Add the test that shows it works, or set it back to in-progress.`);
    } else {
      const problem = proofProblem(item.proof);
      if (problem) problems.push(`${label}: is marked done, but ${problem} Point it at a test that proves the item, or set it back to in-progress.`);
    }
  }
});

const count = (status) => features.filter((item) => item?.status === status).length;
const inProgress = features.filter((item) => item?.status === "in-progress");
if (inProgress.length > 1) {
  problems.push(`${inProgress.length} items are in progress (${inProgress.map((item) => item.id).join(", ")}). Work on one at a time: finish or set back all but one.`);
}

console.log(`Done ${count("done")}, in progress ${count("in-progress")}, to do ${count("todo")}.`);
const next = inProgress[0] ?? features.find((item) => item?.status === "todo");
console.log(next ? `Next: ${next.id}: ${next.description}` : "Next: nothing left to do.");

// The newest entry in the session log, which comes first in the file.
if (existsSync(join(root, LOG))) {
  const lines = readFileSync(join(root, LOG), "utf8").split(/\r?\n/);
  const start = lines.findIndex((line) => line.startsWith("## "));
  if (start >= 0) {
    const end = lines.findIndex((line, j) => j > start && line.startsWith("## "));
    const entry = lines.slice(start, end < 0 ? lines.length : end).filter((line) => line.trim() !== "");
    console.log(`\nLast session (${LOG}):`);
    for (const line of entry) console.log(`  ${line}`);
  }
}
console.log("");
finish();
