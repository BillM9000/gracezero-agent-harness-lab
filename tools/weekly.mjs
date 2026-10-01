// CI's failure rate by week, from GitHub's record of a workflow's runs:
//
//   gh run list --workflow ci.yml --limit 500 --json conclusion,createdAt,headBranch | node tools/weekly.mjs
//
// It reads that JSON on standard input and prints a line a week, oldest first: the Monday the week
// starts on (UTC), and how many of its runs failed. A run that failed, timed out or never started
// counts as a failure; a cancelled or skipped run says nothing about the code, so it's left out.
// --branch NAME counts only the runs on that branch, such as main.
import { parseArgs } from "node:util";

const { branch } = parseArgs({ options: { branch: { type: "string" } } }).values;
const FAILED = new Set(["failure", "timed_out", "startup_failure"]);
let input = "";
for await (const chunk of process.stdin) input += chunk;
const weeks = new Map();
for (const run of JSON.parse(input)) {
  if (branch && run.headBranch !== branch) continue; // --branch: a run on another branch
  if (run.conclusion !== "success" && !FAILED.has(run.conclusion)) continue; // cancelled, skipped: no verdict
  const day = new Date(run.createdAt);
  day.setUTCDate(day.getUTCDate() - ((day.getUTCDay() + 6) % 7)); // back to that week's Monday
  const week = day.toISOString().slice(0, 10);
  const w = weeks.get(week) ?? { runs: 0, failed: 0 };
  w.runs += 1;
  if (FAILED.has(run.conclusion)) w.failed += 1;
  weeks.set(week, w);
}
for (const [week, w] of [...weeks].sort(([a], [b]) => a.localeCompare(b))) {
  console.log(`${week}  ${w.failed} of ${w.runs} failed (${Math.round((100 * w.failed) / w.runs)}%)`);
}
