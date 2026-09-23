// What a failed check sends back to an agent (chapter 25), shared by the Stop hook
// (tools/hooks/stop-check.mjs) and the headless loop (tools/fix-loop.mjs).
//
// An agent can only fix what it's told. The report says which checks failed and ends with their
// output, the way node check.mjs prints it; the rerun command lets it check its own fix; the rules
// say what doesn't count as a fix. The report is bounded, because Claude Code moves long hook
// text into a file the agent isn't asked to read, and its first lines name the failing checks.
import { spawnSync } from "node:child_process";

export const RERUN = "node check.mjs --fast";

export const RULES = [
  "Fix what the checks report, in the code they point at.",
  "Don't weaken or skip a test, a rule or a check to make it pass.",
  "If a check itself is wrong, stop and say why instead of changing it.",
];

// Runs the fast checks in the repository at root. The exit code decides whether they passed; the
// output is only what gets passed on.
export function runFastChecks(root) {
  const run = spawnSync(process.execPath, ["check.mjs", "--fast"], { cwd: root, encoding: "utf8" });
  const output = `${run.stdout ?? ""}${run.stderr ?? ""}${run.error ? run.error.message : ""}`;
  return { passed: run.status === 0, output };
}

// check.mjs prints a PASS line for every check that passed; the agent needs only the failures.
export function failureReport(output, max = 6000) {
  const lines = output.replaceAll("\r\n", "\n").split("\n");
  const kept = lines.filter((line) => !line.startsWith("PASS  ")).join("\n").trim();
  if (kept.length <= max) return kept;
  return `${kept.slice(0, max)}\n[cut at ${max} characters: run ${RERUN} to see the rest]`;
}
