// Builds a made-up history to try tools/measure.mjs on (chapter 26's Try it).
//
//   node tools/measure-demo.mjs <new folder>
//
// Two fortnights of work by one developer and a coding agent, with a change to the harness between
// them: a commit tagged stop-hook that runs the fast checks whenever the agent says it's done
// (chapter 25). Before it, 14 of the agent's 40 changes need a fix, 2 of those are reverts and 3
// fix the same time-zone bug, 3 of its changes silence a rule, and 2 fixes correct the README.
// After it, 4 of 40 need a fix, and 1 corrects the README. It also writes the files a team would
// export beside its history, in the folder's records/: CI runs and merged pull requests in the shape
// the GitHub CLI prints them, and a line of spend for every agent change. None of it is real: the
// numbers are chosen to show the arithmetic, and the dates are fixed, so everyone gets the same.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const BASE = Date.parse("2026-03-02T09:00:00Z");
const HOUR = 60 * 60 * 1000;
const AGENT = "\n\nCo-Authored-By: Claude <noreply@anthropic.com>";
const SILENCED = "import os  # noqa: F401\n";

// Each fortnight: when it starts (hours after BASE), which agent changes a fix follows, which of
// those fixes are reverts or the time-zone bug, which changes silence a rule, which are followed by
// a fix to the README, which fail CI, and the cycles of review hours and dollars.
const PERIODS = [
  {
    start: 0,
    reworked: [1, 3, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35, 38],
    reverts: [8, 26],
    timeZone: [5, 17, 29],
    silenced: [2, 12, 22],
    readme: [10, 30],
    ciFails: (i) => [0, 3, 6].includes(i % 10),
    reviewHours: [2, 3, 4],
    usd: [1.6, 2.1, 2.6],
  },
  {
    start: 344,
    reworked: [7, 17, 27, 37],
    reverts: [],
    timeZone: [],
    silenced: [],
    readme: [20],
    ciFails: (i) => i % 10 === 0,
    reviewHours: [0.5, 1, 1.5],
    usd: [1.3, 1.8, 2.3],
  },
];
const HARNESS_CHANGE = 324; // hours after BASE: after the first fortnight's last commit

const target = process.argv[2];
if (!target) {
  console.error("Usage: node tools/measure-demo.mjs <new folder>");
  process.exit(2);
}
const root = resolve(target);
if (existsSync(root) && readdirSync(root).length) {
  console.error(`measure-demo: ${root} isn't empty; give it a new folder.`);
  process.exit(2);
}
mkdirSync(root, { recursive: true });
const git = (args, env = {}) => {
  const run = spawnSync("git", args, { cwd: root, encoding: "utf8", env: { ...process.env, ...env } });
  if (run.status !== 0) throw new Error(`git ${args.join(" ")} failed: ${run.stderr}`);
  return run.stdout.trim();
};
git(["init", "-q"]);

const commits = []; // { hours }, in the order they're made; their hashes are read at the end
function commit(hours, agent, subject, files) {
  for (const [file, text] of Object.entries(files)) {
    mkdirSync(dirname(join(root, file)), { recursive: true });
    writeFileSync(join(root, file), text);
  }
  const date = new Date(BASE + hours * HOUR).toISOString();
  git(["add", ...Object.keys(files)]);
  git(["-c", "user.name=A Developer", "-c", "user.email=developer@example.com", "commit", "-q", "-m", subject + (agent ? AGENT : "")], {
    GIT_AUTHOR_DATE: date,
    GIT_COMMITTER_DATE: date,
  });
  commits.push({ hours });
  return commits.length - 1;
}

const runs = [];
const prs = [];
const spend = [];
let readme = 0;
PERIODS.forEach((p, period) => {
  // Everything this fortnight does, in time order.
  const events = [];
  for (let i = 0; i < 40; i++) {
    const at = p.start + i * 8;
    const file = `app/feature_${period}_${String(i).padStart(2, "0")}.py`;
    const feature = `feature ${period * 40 + i + 1}`;
    events.push([at, () => {
      const body = `# ${feature}\n${p.silenced.includes(i) ? SILENCED : ""}def run():\n    return ${i}\n`;
      const hash = commit(at, true, `feat: add ${feature}`, { [file]: body });
      runs.push({ headSha: hash, conclusion: p.ciFails(i) ? "failure" : "success", createdAt: new Date(BASE + at * HOUR).toISOString() });
      const review = p.reviewHours[i % p.reviewHours.length];
      prs.push({
        number: prs.length + 1,
        createdAt: new Date(BASE + (at - review) * HOUR).toISOString(),
        mergedAt: new Date(BASE + at * HOUR).toISOString(),
        mergeCommit: { oid: hash },
        commits: [],
      });
      spend.push({ at: new Date(BASE + (at - 0.5) * HOUR).toISOString(), usd: p.usd[i % p.usd.length] });
    }]);
    if (p.reworked.includes(i)) {
      const subject = p.reverts.includes(i)
        ? `Revert "feat: add ${feature}"`
        : p.timeZone.includes(i)
          ? "fix: dates in the wrong time zone"
          : `fix: ${feature} handles an empty list`;
      events.push([at + 1, () => commit(at + 1, false, subject, { [file]: `# ${feature}, fixed\ndef run():\n    return []\n` })]);
    }
    if (p.readme.includes(i)) {
      events.push([at + 2, () => commit(at + 2, false, "fix: the README's setup steps", { "README.md": `# Demo\n\nSetup, corrected ${++readme} time(s).\n` })]);
    }
  }
  events.sort((a, b) => a[0] - b[0]);
  for (const [, run] of events) run();
  if (period === 0) {
    commit(HARNESS_CHANGE, false, "chore: run the fast checks when the agent stops", {
      ".claude/settings.json": `${JSON.stringify({ hooks: { Stop: [] } }, null, 2)}\n`,
    });
    git(["tag", "stop-hook"]);
  }
});

// Every commit's hash, oldest first, in place of the index each record holds so far.
const hashes = git(["log", "--reverse", "--format=%H"]).split("\n");
for (const run of runs) run.headSha = hashes[run.headSha];
for (const pr of prs) pr.mergeCommit.oid = hashes[pr.mergeCommit.oid];
// A superseded run, cancelled: it says nothing about the code, and measure leaves it out.
runs.push({ headSha: hashes.at(-1), conclusion: "cancelled", createdAt: new Date(BASE + commits.at(-1).hours * HOUR).toISOString() });
mkdirSync(join(root, "records"), { recursive: true });
writeFileSync(join(root, "records", "ci-runs.json"), `${JSON.stringify(runs, null, 2)}\n`);
writeFileSync(join(root, "records", "pull-requests.json"), `${JSON.stringify(prs, null, 2)}\n`);
writeFileSync(join(root, "records", "spend.jsonl"), spend.map((line) => JSON.stringify(line)).join("\n") + "\n");
console.log(`Built a made-up history of ${commits.length} commits in ${root}, with its records.`);
console.log(`Next: node tools/measure.mjs ${target} --at stop-hook --days 14 --known "time zone" --save records/baseline.json`);
