// The day node check.mjs checks the models' retirement dates as of (chapter 20).
//
// python -m agent_policy fails a definition whose model may retire within the policy's notice, so run
// against today's date it starts failing on its own once a model's notice window opens, with no
// change to the code, and so do the checks and commands that refuse on a policy failure. For a check
// run that must give the same answer on any day (a reader's clone, CI on a push, a chapter's tag),
// check.mjs fixes the day, through the AGENT_POLICY_TODAY variable python/src/agent_policy reads, to
// the day recorded in one place: the "read" date in python/agents/models.toml, the day its dates were
// copied from the provider's page. The dates can't be trusted past the day they were read anyway;
// when someone reads the page again and updates the file, the checks move forward with it.
//
// Today's date is still checked, where that's the point: python -m agent_policy on its own, and the
// nightly workflow's retirement job, which runs it that way. A caller who sets AGENT_POLICY_TODAY
// (YYYY-MM-DD) gets that day instead of the pinned one.
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const VARIABLE = "AGENT_POLICY_TODAY";
export const DATE_FILE = "python/agents/models.toml";
const DAY = /^\d{4}-\d{2}-\d{2}$/;

// The "read = YYYY-MM-DD" line of the models file, as a string.
export function pinnedDay(root) {
  const text = readFileSync(join(root, DATE_FILE), "utf8");
  const found = /^read\s*=\s*(\d{4}-\d{2}-\d{2})\s*$/m.exec(text);
  if (!found) {
    throw new Error(`${DATE_FILE} has no "read = YYYY-MM-DD" line, the day its dates were copied, so there is no day to check them as of.`);
  }
  return found[1];
}

// The environment every check runs in: the caller's, with AGENT_POLICY_TODAY set to the pinned day
// unless the caller set it.
export function checkEnvironment(root, env = process.env) {
  const given = env[VARIABLE];
  if (given !== undefined && given !== "" && !DAY.test(given)) {
    throw new Error(`${VARIABLE} is ${JSON.stringify(given)}; set it to a day, such as 2027-04-01, or unset it to check as of ${DATE_FILE}'s read date.`);
  }
  return { ...env, [VARIABLE]: given || pinnedDay(root) };
}
