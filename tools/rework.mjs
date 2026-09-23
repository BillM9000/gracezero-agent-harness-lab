// Where agent work gets redone (chapter 31): a week-one measurement that needs nothing but the
// repository's history.
//
//   node tools/rework.mjs [path] [--days N] [--within N] [--depth N] [--ignore REGEX] [--all-files]
//
// For the --days (90) up to the latest commit, it counts the commits that name a coding agent as
// author or co-author, and the fixes: commits whose subject starts with fix, hotfix or revert. A
// fix is rework when a file it changes was last changed by an agent commit less than --within (14)
// days before. The report groups rework by folder, --depth (2) levels deep, next to how many agent
// commits touched that folder and the median time from the agent's change to the fix, then lists
// the files it counted most often.
//
// Some files change with every commit or every release, and would make every fix look like
// rework: Markdown files (changelogs, handoff notes) are left out unless you pass --all-files, and
// --ignore leaves out files matching a regular expression, such as a package.json whose version
// every release bumps. The list of files counted most often is where to spot them.
//
// It's a pointer, not a verdict: commit messages are whatever their authors wrote, a fix can
// correct a person's line in a file an agent also touched, and a squashed merge hides the commits
// inside it. Read the fixes it counts before you believe the table.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export const AGENT = /\b(claude|copilot|codex|cursor|devin|gemini|aider|windsurf|jules)\b/i;
export const FIX = /^(fix(es|ed)?|hotfix|revert(s|ed)?)\b/i;
const MARKDOWN = /\.md$/i;
const DAY = 24 * 60 * 60;

function option(args, name, fallback) {
  const at = args.indexOf(name);
  if (at < 0) return fallback;
  const value = Number(args[at + 1]);
  if (!Number.isInteger(value) || value < 1) throw new Error(`${name} needs a whole number of 1 or more.`);
  return value;
}

// Commits oldest first, each with its time, subject, author, co-authors and the files it counts.
export function readHistory(root, sinceSeconds, { allFiles = false, ignore = null } = {}) {
  // Committer time, the date --since filters on.
  const format = "%x1e%ct%x1f%s%x1f%an%x1f%(trailers:key=Co-authored-by,valueonly,separator=%x1d)%x1f";
  const since = new Date(sinceSeconds * 1000).toISOString();
  const log = spawnSync("git", ["log", "--no-merges", "--reverse", `--since=${since}`, `--format=${format}`, "--name-only"], {
    cwd: root,
    encoding: "utf8",
    maxBuffer: 256 * 1024 * 1024,
  });
  if (log.status !== 0) throw new Error(`git log failed in ${root}: ${log.stderr.trim()}`);
  const counted = (f) => f && (allFiles || !MARKDOWN.test(f)) && !(ignore && ignore.test(f));
  return log.stdout
    .split("\x1e")
    .filter((entry) => entry.trim())
    .map((entry) => {
      const [time, subject, author, coauthors, files] = entry.split("\x1f");
      return {
        time: Number(time),
        subject,
        author,
        coauthors: coauthors.split("\x1d").filter(Boolean),
        files: files.split("\n").map((f) => f.trim()).filter(counted),
      };
    });
}

export const isAgent = (commit) => AGENT.test(commit.author) || commit.coauthors.some((c) => AGENT.test(c));
export const isFix = (commit) => FIX.test(commit.subject.trim());

export function folder(file, depth) {
  const parts = file.split("/").slice(0, -1);
  return parts.length ? parts.slice(0, depth).join("/") : "(root)";
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

// history must reach back `within` days before the window, so a fix early in the window can see
// the agent change it corrects.
export function rework(history, { windowStart, within, depth }) {
  const last = new Map();
  const areas = new Map();
  const files = new Map();
  const area = (name) => {
    if (!areas.has(name)) areas.set(name, { agentCommits: 0, reworkFixes: 0, hours: [] });
    return areas.get(name);
  };
  const totals = { commits: 0, agentCommits: 0, fixes: 0, reworkFixes: 0 };
  for (const commit of history) {
    const agent = isAgent(commit);
    if (commit.time >= windowStart) {
      totals.commits++;
      if (agent) totals.agentCommits++;
      if (agent) for (const name of new Set(commit.files.map((f) => folder(f, depth)))) area(name).agentCommits++;
      if (isFix(commit)) {
        totals.fixes++;
        const reworked = commit.files.filter((f) => {
          const before = last.get(f);
          return before && before.agent && commit.time - before.time < within * DAY;
        });
        if (reworked.length) totals.reworkFixes++;
        for (const f of reworked) files.set(f, (files.get(f) ?? 0) + 1);
        // Once per folder, however many of its files the fix changes; the gap is the shortest there.
        for (const name of new Set(reworked.map((f) => folder(f, depth)))) {
          const gaps = reworked.filter((f) => folder(f, depth) === name).map((f) => commit.time - last.get(f).time);
          area(name).reworkFixes++;
          area(name).hours.push(Math.min(...gaps) / 3600);
        }
      }
    }
    for (const f of commit.files) last.set(f, { agent, time: commit.time });
  }
  const rows = [...areas.entries()]
    .filter(([, a]) => a.reworkFixes > 0)
    .map(([name, a]) => ({ area: name, agentCommits: a.agentCommits, reworkFixes: a.reworkFixes, medianHours: median(a.hours) }))
    .sort((x, y) => y.reworkFixes - x.reworkFixes || x.area.localeCompare(y.area));
  const top = [...files.entries()].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0])).slice(0, 5);
  return { totals, rows, top };
}

const percent = (part, whole) => (whole ? `${Math.round((100 * part) / whole)}%` : "-");

export function report({ totals, rows, top }, { days, within, depth, allFiles, ignore }) {
  const lines = [
    `rework: ${totals.commits} commits in the ${days} days up to the latest; ${totals.agentCommits} (${percent(totals.agentCommits, totals.commits)}) name an agent as author or co-author.`,
    `${totals.fixes} are fixes; ${totals.reworkFixes} of them change a file an agent commit had changed in the ${within} days before.`,
  ];
  const left = [allFiles ? null : "Markdown files", ignore ? `files matching ${ignore}` : null].filter(Boolean);
  if (left.length) lines.push(`Left out: ${left.join(" and ")}.`);
  if (!rows.length) return [...lines, "", "No fix reworked recent agent work."].join("\n");
  const width = Math.max(6, ...rows.map((r) => r.area.length));
  lines.push("", `Where fixes landed on recent agent work (by folder, ${depth} level${depth === 1 ? "" : "s"}):`);
  lines.push(`  ${"folder".padEnd(width)}  agent commits  rework fixes  rate  median time to fix`);
  for (const r of rows) {
    const cells = [
      String(r.agentCommits).padStart(13),
      String(r.reworkFixes).padStart(12),
      percent(r.reworkFixes, r.agentCommits).padStart(4),
      `${r.medianHours.toFixed(1)} h`.padStart(17),
    ];
    lines.push(`  ${r.area.padEnd(width)}  ${cells.join("  ")}`);
  }
  lines.push("", "Files counted most often (if one changes with every release, leave it out with --ignore):");
  for (const [file, count] of top) lines.push(`  ${String(count).padStart(4)}  ${file}`);
  return lines.join("\n");
}

export function main(args) {
  const values = new Set(["--days", "--within", "--depth", "--ignore"]);
  const root = args.find((a, i) => !a.startsWith("--") && !(i > 0 && values.has(args[i - 1]))) ?? ".";
  const days = option(args, "--days", 90);
  const within = option(args, "--within", 14);
  const depth = option(args, "--depth", 2);
  const allFiles = args.includes("--all-files");
  const at = args.indexOf("--ignore");
  const ignore = at >= 0 ? new RegExp(args[at + 1]) : null;
  // The window ends at the latest commit, not today, so a run at the same commit gives the same table.
  const latest = spawnSync("git", ["log", "-1", "--format=%ct"], { cwd: root, encoding: "utf8" });
  if (latest.status !== 0 || !latest.stdout.trim()) throw new Error(`${root} isn't a git repository with commits.`);
  const windowStart = Number(latest.stdout.trim()) - days * DAY;
  const history = readHistory(root, windowStart - within * DAY, { allFiles, ignore });
  return report(rework(history, { windowStart, within, depth }), { days, within, depth, allFiles, ignore });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    console.log(main(process.argv.slice(2)));
  } catch (error) {
    console.error(
      `rework: ${error.message}\nUsage: node tools/rework.mjs [path] [--days N] [--within N] [--depth N] [--ignore REGEX] [--all-files]`,
    );
    process.exit(2);
  }
}
