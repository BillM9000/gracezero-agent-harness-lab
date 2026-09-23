// Shows where the lab's work stands, and checks that the work list can be trusted (chapter 10).
//
// progress/features.json lists the work, each item todo, in-progress or done. The list is only
// useful to the next session if "done" means something, so this fails when:
//   - an item marked done names no proof, or names a test that doesn't exist;
//   - more than one item is in progress (one unit of work at a time);
//   - an item is malformed, or two items share an id.
// It checks that each proof test exists; node check.mjs runs the tests themselves.
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

// Does the proof name a test that exists? A Python test is a def with that name; a JavaScript or
// TypeScript test is a test(...) or it(...) call with that title.
function proofProblem(proof) {
  const match = /^([^:]+)::(.+)$/.exec(proof);
  if (!match) return `"${proof}" isn't a proof. Write it as <test file>::<test name>.`;
  const [, file, name] = match;
  if (!tracked.has(file)) return `its proof file, ${file}, isn't in the repository.`;
  const text = readFileSync(join(root, file), "utf8");
  const found = file.endsWith(".py")
    ? new RegExp(`^\\s*(async\\s+)?def ${escape(name)}\\(`, "m").test(text)
    : new RegExp(`\\b(test|it)\\(\\s*["'\`]${escape(name)}["'\`]`).test(text);
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
