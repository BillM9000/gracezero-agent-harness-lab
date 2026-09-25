// The harness's numbers, and a baseline to hold them against (chapter 26).
//
//   node tools/measure.mjs [path] [--days N] [--within N] [--at REV] [--records DIR]
//                          [--known TEXT]... [--ignore REGEX] [--save FILE] [--against FILE]
//
// From the git history of the --days (90) up to REV (default: the latest commit):
//   agent changes    commits that name a coding agent as author or co-author (tools/rework.mjs)
//   rework           fixes that change a file an agent commit changed in the --within (14) days
//                    before, per agent change: chapter 31's count, for the whole repository
//   reverts          rework fixes whose subject starts with revert
//   rules silenced   lines agent changes add that switch a rule off (tools/silenced.mjs)
//   drift fixes      fixes that change documentation (Markdown) and nothing else
//   known failures   fixes whose subject contains a --known text, one row each
// From the files in the records folder (--records, default <path>/records), when they're there:
//   fix-loop.jsonl      tools/fix-loop.mjs --record: rule violations sent back to an agent, and what
//                       its next attempt did about each (every line in the file, not a window)
//   ci-runs.json        gh run list --json headSha,conclusion: CI's pass rate on agent changes
//   pull-requests.json  gh pr list --state merged --json createdAt,mergedAt,mergeCommit,commits:
//                       how long pull requests with agent changes waited, opened to merged
//   spend.jsonl         a line per call or per day, each with at and usd: AI spend per agent change
//                       (python -m helpdesk.gate run --record writes lines of that shape)
//
// --save writes the numbers to a file. --against compares them with a file saved earlier, over a
// window of the same length, and says whether a change in a rate is more than noise.
//
// Every number here is a proxy that a person should read before believing: the counts depend on
// commit subjects, trailers and patterns (see tools/rework.mjs and tools/silenced.mjs), and the
// report lists what it counted where a list fits.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { isAgent, isFix, readHistory, rework } from "./rework.mjs";
import { addedLines, silenced } from "./silenced.mjs";

const DAY = 24 * 60 * 60;
const MARKDOWN = /\.md$/i;
const REVERT = /^revert/i;
// Conclusions that say how the code did. A cancelled or skipped run says nothing about it.
const PASSED = new Set(["success"]);
const FAILED = new Set(["failure", "timed_out", "startup_failure"]);
export const FEWEST = 30; // agent changes a side, below which a change in a rate isn't called
const Z_95 = 1.96;

function git(root, args) {
  const run = spawnSync("git", args, { cwd: root, encoding: "utf8", maxBuffer: 1024 * 1024 * 1024 });
  if (run.status !== 0) throw new Error(`git ${args[0]} failed in ${root}: ${(run.stderr ?? "").trim()}`);
  return run.stdout;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

// Lines each commit in the window adds, by hash.
function addedByCommit(root, rev, since) {
  const out = git(root, ["log", rev, "--no-merges", `--since=${since}`, "--format=%x1e%H", "-p", "--unified=0", "--no-color", "--no-ext-diff"]);
  const byCommit = new Map();
  for (const entry of out.split("\x1e").filter((e) => e.trim())) {
    const newline = entry.indexOf("\n");
    const hash = (newline < 0 ? entry : entry.slice(0, newline)).trim();
    byCommit.set(hash, newline < 0 ? [] : addedLines(entry.slice(newline + 1)));
  }
  return byCommit;
}

function readJsonLines(path) {
  return readFileSync(path, "utf8")
    .split("\n")
    .map((line, i) => [line, i + 1])
    .filter(([line]) => line.trim())
    .map(([line, number]) => {
      try {
        return JSON.parse(line);
      } catch {
        throw new Error(`${path}:${number} isn't a JSON line.`);
      }
    });
}

// The loop's record: every attempt, whatever the window.
export function loopMeasures(entries) {
  const outcomes = {};
  const byCheck = {};
  for (const e of entries) {
    outcomes[e.outcome] = (outcomes[e.outcome] ?? 0) + 1;
    for (const check of e.failing ?? []) byCheck[check] = (byCheck[check] ?? 0) + 1;
  }
  const n = (name) => outcomes[name] ?? 0;
  return {
    attempts: entries.length,
    fixed: n("fixed"),
    silencedOrChanged: n("silenced a rule") + n("changed the checks"),
    other: entries.length - n("fixed") - n("silenced a rule") - n("changed the checks"),
    byCheck,
  };
}

// CI runs on agent changes: a pass rate over runs that finished with a verdict on the code.
export function ciMeasures(runs, agentHashes) {
  const mine = runs.filter((r) => agentHashes.has(r.headSha));
  const passed = mine.filter((r) => PASSED.has(r.conclusion)).length;
  const judged = passed + mine.filter((r) => FAILED.has(r.conclusion)).length;
  return { runs: judged, passed };
}

// Merged pull requests with an agent change, opened to merged, inside the window.
export function reviewMeasures(prs, agentHashes, start, end) {
  const hours = prs
    .filter((p) => p.mergedAt && p.createdAt)
    .filter((p) => {
      const merged = Date.parse(p.mergedAt) / 1000;
      return merged >= start && merged <= end;
    })
    .filter((p) => agentHashes.has(p.mergeCommit?.oid) || (p.commits ?? []).some((c) => agentHashes.has(c.oid)))
    .map((p) => (Date.parse(p.mergedAt) - Date.parse(p.createdAt)) / 3600000);
  return { prs: hours.length, medianHours: median(hours) };
}

export function spendMeasures(lines, start, end) {
  const inWindow = lines.filter((l) => {
    const at = Date.parse(l.at) / 1000;
    return at >= start && at <= end && typeof l.usd === "number";
  });
  return { lines: inWindow.length, usd: inWindow.reduce((sum, l) => sum + l.usd, 0) };
}

export function measure(root, { days = 90, within = 14, rev = "HEAD", records = null, known = [], ignore = null } = {}) {
  const [hash, time] = git(root, ["log", "-1", "--format=%h %ct", rev]).trim().split(" ");
  const end = Number(time);
  const start = end - days * DAY;
  const since = new Date(start * 1000).toISOString();
  const history = readHistory(root, start - within * DAY, { ignore, rev });
  const counted = rework(history, { windowStart: start, within, depth: 1 });
  const inWindow = history.filter((c) => c.time >= start);
  const agentHashes = new Set(inWindow.filter(isAgent).map((c) => c.hash));
  const reworkFixes = counted.fixes.filter((f) => f.rework);

  const allFiles = readHistory(root, start, { allFiles: true, rev });
  const driftFixes = allFiles.filter((c) => isFix(c) && c.files.length && c.files.every((f) => MARKDOWN.test(f)));

  const added = addedByCommit(root, rev, since);
  const silencedLines = [];
  for (const h of agentHashes) {
    const lines = (added.get(h) ?? []).filter(({ file }) => !(ignore && ignore.test(file)));
    silencedLines.push(...silenced(lines));
  }

  const result = {
    about: "tools/measure.mjs (chapter 26): a harness's numbers over one window of its history.",
    repository: root,
    end: { hash, date: new Date(end * 1000).toISOString().slice(0, 10) },
    days,
    within,
    ignore: ignore ? String(ignore) : null,
    commits: inWindow.length,
    agentChanges: agentHashes.size,
    reworkFixes: reworkFixes.length,
    reverts: reworkFixes.filter((f) => REVERT.test(f.subject.trim())).length,
    medianHoursToFix: median(reworkFixes.map((f) => f.hours)),
    silenced: silencedLines.length,
    driftFixes: driftFixes.length,
    known: Object.fromEntries(known.map((text) => [text, counted.fixes.filter((f) => f.subject.toLowerCase().includes(text.toLowerCase())).length])),
    loop: null,
    ci: null,
    review: null,
    spend: null,
  };
  const found = {};
  if (records && existsSync(records)) {
    const file = (name) => (existsSync(join(records, name)) ? join(records, name) : null);
    if ((found.loop = file("fix-loop.jsonl"))) result.loop = loopMeasures(readJsonLines(found.loop));
    if ((found.ci = file("ci-runs.json"))) result.ci = ciMeasures(JSON.parse(readFileSync(found.ci, "utf8")), agentHashes);
    if ((found.review = file("pull-requests.json")))
      result.review = reviewMeasures(JSON.parse(readFileSync(found.review, "utf8")), agentHashes, start, end);
    if ((found.spend = file("spend.jsonl"))) result.spend = spendMeasures(readJsonLines(found.spend), start, end);
  }
  return { result, silencedLines, found };
}

const pct = (part, whole) => (whole ? `${Math.round((100 * part) / whole)}%` : "-");
const hoursText = (h) => (h === null || h === undefined ? "-" : `${h.toFixed(1)} h`);

// A 95% interval for the difference of two proportions, by the normal approximation.
export function change(beforePart, beforeWhole, nowPart, nowWhole) {
  if (beforeWhole < FEWEST || nowWhole < FEWEST) return { tooFew: true };
  const p1 = beforePart / beforeWhole;
  const p2 = nowPart / nowWhole;
  if (p1 > 1 || p2 > 1) return { tooFew: true };
  const error = Math.sqrt((p1 * (1 - p1)) / beforeWhole + (p2 * (1 - p2)) / nowWhole);
  const d = p2 - p1;
  return { d, low: d - Z_95 * error, high: d + Z_95 * error };
}

export function describe(name, c) {
  if (c.tooFew) return `${name}: fewer than ${FEWEST} on a side, too few to tell a change from noise.`;
  const points = (x) => `${x > 0 ? "+" : ""}${Math.round(100 * x)}`;
  const verdict = c.low > 0 || c.high < 0 ? "more than noise" : "within noise";
  const way = c.d < 0 ? "down" : "up";
  return `${name}: ${way} ${Math.abs(Math.round(100 * c.d))} points (95% interval ${points(c.low)} to ${points(c.high)}): ${verdict}.`;
}

// The rows of the table: a label, and what to print for a measure (null when not measured).
function rows(m, where) {
  const missing = (name) => `not measured: no ${where}/${name}`;
  const known = Object.entries(m.known).map(([text, n]) => [`known failure: "${text}"`, String(n)]);
  return [
    ["agent changes", `${m.agentChanges} of ${m.commits} commits`],
    ["rework fixes per agent change", `${m.reworkFixes} (${pct(m.reworkFixes, m.agentChanges)})`],
    ["  reverts among them", String(m.reverts)],
    ["  median time from change to fix", hoursText(m.medianHoursToFix)],
    ["lines that silence a rule", String(m.silenced)],
    ["drift fixes (documentation alone)", String(m.driftFixes)],
    ...known,
    ["violations sent back to an agent", m.loop ? String(m.loop.attempts) : missing("fix-loop.jsonl")],
    ["  its next change fixed the code", m.loop ? String(m.loop.fixed) : ""],
    ["  it silenced a rule or a check", m.loop ? String(m.loop.silencedOrChanged) : ""],
    ["CI pass rate on agent changes", m.ci ? `${m.ci.passed} of ${m.ci.runs} (${pct(m.ci.passed, m.ci.runs)})` : missing("ci-runs.json")],
    ["review time, agent pull requests", m.review ? `${hoursText(m.review.medianHours)} median of ${m.review.prs}` : missing("pull-requests.json")],
    ["AI spend per agent change", m.spend ? `$${m.agentChanges ? (m.spend.usd / m.agentChanges).toFixed(2) : "-"}` : missing("spend.jsonl")],
  ].filter(([, value]) => value !== "");
}

function header(m) {
  const left = ["Markdown files", m.ignore ? `files matching ${m.ignore}` : null].filter(Boolean).join(" and ");
  return `${m.repository} at ${m.end.hash}, the ${m.days} days up to ${m.end.date}. Left out: ${left}.`;
}

export function report({ result: m, silencedLines }, where, baseline = null) {
  const lines = [];
  if (!baseline) {
    lines.push(`measure: ${header(m)}`, "");
    const table = rows(m, where);
    const width = Math.max(...table.map(([label]) => label.length));
    for (const [label, value] of table) lines.push(`${label.padEnd(width)}  ${value}`);
  } else {
    lines.push(`measure: ${header(m)}`, `Baseline: ${header(baseline)}`, "");
    if (baseline.days !== m.days) lines.push(`The windows differ (${baseline.days} and ${m.days} days): compare windows of the same length.`, "");
    const now = rows(m, where);
    const before = new Map(rows(baseline, where).map(([label, value]) => [label, value]));
    const width = Math.max(...now.map(([label]) => label.length));
    const cell = (v) => (v.startsWith("not measured") ? "-" : v);
    const w = Math.max(8, ...now.map(([label]) => cell(before.get(label) ?? "-").length));
    lines.push(`${"".padEnd(width)}  ${"baseline".padStart(w)}  now`);
    for (const [label, value] of now) {
      const was = cell(before.get(label) ?? "-");
      if (was === "-" && cell(value) === "-") continue; // measured on neither side
      lines.push(`${label.padEnd(width)}  ${was.padStart(w)}  ${cell(value)}`);
    }
    lines.push("");
    lines.push(describe("Rework per agent change", change(baseline.reworkFixes, baseline.agentChanges, m.reworkFixes, m.agentChanges)));
    if (m.ci && baseline.ci) lines.push(describe("CI pass rate on agent changes", change(baseline.ci.passed, baseline.ci.runs, m.ci.passed, m.ci.runs)));
  }
  if (silencedLines.length) {
    lines.push("", "Lines that silence a rule, as counted (read them before you believe the count):");
    const clip = (line) => (line.length > 96 ? `${line.slice(0, 93)}...` : line);
    for (const line of silencedLines.slice(0, 8)) lines.push(`  ${clip(line)}`);
    if (silencedLines.length > 8) lines.push(`  and ${silencedLines.length - 8} more`);
  }
  return lines.join("\n");
}

function option(args, name) {
  const at = args.indexOf(name);
  return at < 0 ? undefined : args[at + 1];
}

function whole(args, name, fallback) {
  const raw = option(args, name);
  if (raw === undefined) return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1) throw new Error(`${name} needs a whole number of 1 or more.`);
  return value;
}

export function main(args) {
  const values = new Set(["--days", "--within", "--at", "--records", "--known", "--ignore", "--save", "--against"]);
  const root = args.find((a, i) => !a.startsWith("--") && !(i > 0 && values.has(args[i - 1]))) ?? ".";
  const against = option(args, "--against");
  const baseline = against ? JSON.parse(readFileSync(against, "utf8")) : null;
  const days = whole(args, "--days", baseline?.days ?? 90);
  const within = whole(args, "--within", baseline?.within ?? 14);
  const ignoreText = option(args, "--ignore");
  const known = args.flatMap((a, i) => (a === "--known" && args[i + 1] ? [args[i + 1]] : []));
  const records = option(args, "--records") ?? join(root, "records");
  const measured = measure(root, {
    days,
    within,
    rev: option(args, "--at") ?? "HEAD",
    records,
    known: known.length ? known : Object.keys(baseline?.known ?? {}),
    ignore: ignoreText ? new RegExp(ignoreText) : null,
  });
  const where = (relative(process.cwd(), records) || ".").replaceAll("\\", "/");
  const out = [report(measured, where, baseline)];
  const save = option(args, "--save");
  if (save) {
    mkdirSync(dirname(save), { recursive: true });
    writeFileSync(save, `${JSON.stringify(measured.result, null, 2)}\n`);
    out.push("", `Saved to ${save}.`);
  }
  return out.join("\n");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    console.log(main(process.argv.slice(2)));
  } catch (error) {
    console.error(
      `measure: ${error.message}\nUsage: node tools/measure.mjs [path] [--days N] [--within N] [--at REV] [--records DIR] [--known TEXT]... [--ignore REGEX] [--save FILE] [--against FILE]`,
    );
    process.exit(2);
  }
}
