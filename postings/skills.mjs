// What one kind of job asks for, and where the book and this lab build each skill (chapter 32).
//
//   node postings/skills.mjs <postings.json> --type KIND [--also] [--evidence]
//
// It counts, among the sample's postings of one kind, how many ask for each skill the codebook
// codes (the thirteen signals and five languages), and names the chapters that build each one from
// postings/skills-map.json. Then it lays out a path through the book for that kind: Part I, the
// parts chapter 1's table names, then the other chapters ranked by what these postings ask for
// most, then the rest. --also counts postings that have the kind as their second kind too.
// --evidence adds, for each chapter on the path, the lab files and the checks in node check.mjs
// that show the work, and what the lab alone can't show, such as anything that needs a real model.
//
// The counts come from the sample on every run; the map holds no counts. Before printing anything,
// it checks the map against the sample and the repository: every skill is built by some chapter or
// named as not covered, every lab path is a file git tracks, and every check is one node check.mjs
// runs. Any problem stops the run, with what to fix, so the map can't quietly fall behind.
//
// Exit codes: 0 printed, 1 the map or the sample has problems (each one is listed), 2 usage.
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { listFiles } from "../tools/harness-inventory.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const TYPES = ["enablement", "coding-agents", "product-agents", "applied", "infrastructure"];
const LANGUAGES = ["python", "typescriptOrJavascript", "go", "java", "dotnet"];

const args = process.argv.slice(2);
const option = (name) => {
  const at = args.indexOf(name);
  return at === -1 ? undefined : args[at + 1];
};
const file = args[0];
const type = option("--type");
const mapFile = option("--map") ?? join(HERE, "skills-map.json");
if (!file || file.startsWith("--") || !TYPES.includes(type)) {
  console.error("usage: node postings/skills.mjs <postings.json> --type KIND [--also] [--evidence]");
  console.error(`KIND is one of: ${TYPES.join(", ")}.`);
  process.exit(2);
}
const also = args.includes("--also");
const evidence = args.includes("--evidence");

const sample = JSON.parse(readFileSync(file, "utf8"));
const map = JSON.parse(readFileSync(mapFile, "utf8"));

// The signals are whatever the sample's codebook codes, so a signal added to the codebook must be
// placed in the map before anything prints. The codebook's other entries are named here: the kind of
// job, the languages, and the fields that record when and how each posting was coded.
const NOT_SIGNALS = ["type", "languages", "readOn", "screenedOn", "gatewayBasis", "publicWorkAsked"];
const SIGNALS = Object.keys(sample.codebook ?? {}).filter((key) => !NOT_SIGNALS.includes(key));
const SKILLS = [...SIGNALS, ...LANGUAGES];

function checkLabels() {
  const run = spawnSync(process.execPath, ["check.mjs", "--list"], { cwd: ROOT, encoding: "utf8" });
  if (run.status !== 0) throw new Error(`node check.mjs --list failed: ${run.stderr.trim()}`);
  return new Set(run.stdout.split("\n").map((line) => line.trim()).filter(Boolean));
}

function problemsIn() {
  const problems = [];
  if (!SIGNALS.length) problems.push(`${file}: its codebook names no signals. Use the sample's codebook.`);
  for (const p of sample.postings ?? []) {
    if (!TYPES.includes(p.type)) problems.push(`${p.id}: type is ${JSON.stringify(p.type)}. node postings/tally.mjs ${file} lists every problem in the sample.`);
    for (const key of SKILLS) {
      if (typeof p[key] !== "boolean") problems.push(`${p.id}: "${key}" isn't true or false. node postings/tally.mjs ${file} lists every problem in the sample.`);
    }
  }

  const tracked = listFiles(ROOT);
  const inRepo = (path) => (path.endsWith("/") ? tracked.some((f) => f.startsWith(path)) : tracked.includes(path));
  const labels = checkLabels();
  const seen = new Set();
  for (const ch of map.chapters) {
    const who = `chapter ${ch.chapter}`;
    if (seen.has(ch.chapter)) problems.push(`${who} is listed twice. Give each chapter one entry.`);
    seen.add(ch.chapter);
    for (const skill of ch.builds) {
      if (!SKILLS.includes(skill)) problems.push(`${who} builds "${skill}", which the codebook doesn't code. Use one of: ${SKILLS.join(", ")}.`);
    }
    for (const path of ch.lab) {
      if (inRepo(path)) continue;
      problems.push(
        existsSync(join(ROOT, path))
          ? `${who}: ${path} is on disk but not tracked by git, so no one else has it. Add it with git add, or fix the path.`
          : `${who}: ${path} isn't in the repository. Fix the path, or restore the file.`,
      );
    }
    for (const label of ch.checks) {
      if (!labels.has(label)) problems.push(`${who}: "${label}" isn't a check node check.mjs runs. Copy the name from node check.mjs --list.`);
    }
  }
  for (const skill of SKILLS) {
    const built = map.chapters.some((ch) => ch.builds.includes(skill));
    const excused = skill in (map.notCovered ?? {});
    if (!built && !excused) problems.push(`"${skill}" is built by no chapter. Add it to the chapters that build it, or say why in notCovered.`);
    if (built && excused) problems.push(`"${skill}" is built by a chapter and also listed in notCovered. Keep one.`);
  }
  const inParts = map.parts.flatMap((part) => part.chapters);
  for (const ch of map.chapters) {
    const n = inParts.filter((c) => c === ch.chapter).length;
    if (n !== 1) problems.push(`chapter ${ch.chapter} is in ${n} parts. Put it in exactly one.`);
  }
  for (const t of TYPES) {
    if (!map.start?.[t]) problems.push(`start has no entry for ${t}. Copy chapter 1's table for it.`);
    for (const step of map.start?.[t]?.steps ?? []) {
      if (typeof step === "number" ? !seen.has(step) : !map.parts.some((part) => part.id === step)) {
        problems.push(`start.${t}: ${JSON.stringify(step)} is neither a part nor a chapter in the map.`);
      }
    }
  }
  return problems;
}

const problems = problemsIn();
if (problems.length) {
  console.error(`${mapFile}: ${problems.length} problem(s). Nothing was printed.`);
  for (const line of problems) console.error(`- ${line}`);
  process.exit(1);
}

const posts = sample.postings.filter((p) => p.type === type || (also && p.alsoType === type));
const second = sample.postings.filter((p) => p.alsoType === type).length;
const count = (skill) => posts.filter((p) => p[skill]).length;
const order = new Map(map.chapters.map((ch, i) => [ch.chapter, i]));
const byChapter = new Map(map.chapters.map((ch) => [ch.chapter, ch]));
const builders = (skill) => map.chapters.filter((ch) => ch.builds.includes(skill)).map((ch) => ch.chapter);
const of = (k) => `${k} of ${posts.length}`;

console.log(`# Skills for ${type} jobs, from ${file}\n`);
if (also) {
  console.log(`${posts.length} of ${sample.postings.length} postings have ${type} as their primary or second kind.\n`);
} else {
  const more = second ? ` ${second} more ${second === 1 ? "has" : "have"} it as a second kind; --also counts ${second === 1 ? "it" : "them"}.` : "";
  console.log(`${posts.length} of ${sample.postings.length} postings have ${type} as their primary kind.${more}\n`);
}

function table(title, heading, skills) {
  console.log(`## ${title}\n\n| ${heading} | Postings | Chapters that build it |\n|---|---|---|`);
  const rows = skills.map((s) => [s, count(s)]).sort((a, b) => b[1] - a[1] || skills.indexOf(a[0]) - skills.indexOf(b[0]));
  for (const [skill, k] of rows) {
    const where = skill in (map.notCovered ?? {}) ? map.notCovered[skill] : builders(skill).join(", ");
    console.log(`| ${skill} | ${of(k)} | ${where} |`);
  }
  console.log("");
}
table("What they ask for", "Skill", SIGNALS);
table("Languages they name", "Language", LANGUAGES);

// The path: Part I, then chapter 1's table for this kind, then the rest ranked by the signals.
const used = new Set();
const take = (chapters) => chapters.filter((c) => byChapter.has(c) && !used.has(c)).map((c) => (used.add(c), c));
const span = (cs) =>
  cs.length > 2 && cs.every((c, i) => i === 0 || c === cs[i - 1] + 1)
    ? `chapters ${cs[0]} to ${cs.at(-1)}`
    : cs.length > 1
      ? `chapters ${cs.slice(0, -1).join(", ")} and ${cs.at(-1)}`
      : `chapter ${cs[0]}`;
const partOf = (id) => map.parts.find((part) => part.id === id);
const path = [];

console.log("## A path through the book\n");
const first = partOf("I");
path.push(...take(first.chapters));
console.log(`1. Every path starts with Part I, ${first.name}: ${span(first.chapters)}.`);
const start = map.start[type];
console.log(`2. Then ${start.note}.`);
for (const step of start.steps) {
  if (typeof step === "number") {
    path.push(...take([step]));
    console.log(`   - Chapter ${step}, ${byChapter.get(step).title}`);
  } else {
    const part = partOf(step);
    const cs = take(part.chapters);
    path.push(...cs);
    console.log(`   - Part ${part.id}, ${part.name}: ${span(cs)}`);
  }
}
// Each remaining chapter goes under the signal it builds that most of these postings ask for (a
// tie goes to the signal the codebook lists first), and the groups come most-asked first.
const ranked = map.chapters
  .filter((ch) => !used.has(ch.chapter))
  .map((ch) => {
    const asked = SIGNALS.filter((s) => ch.builds.includes(s) && count(s) > 0);
    const skill = asked.sort((a, b) => count(b) - count(a))[0];
    return { chapter: ch.chapter, skill, k: skill ? count(skill) : 0 };
  })
  .filter((r) => r.skill)
  .sort((a, b) => b.k - a.k || SIGNALS.indexOf(a.skill) - SIGNALS.indexOf(b.skill) || order.get(a.chapter) - order.get(b.chapter));
if (ranked.length) {
  console.log("3. Then the other chapters, by how many of these postings ask for what they build:");
  for (const k of [...new Set(ranked.map((r) => r.k))]) {
    const groups = [...new Set(ranked.filter((r) => r.k === k).map((r) => r.skill))].map((skill) => {
      const cs = take(ranked.filter((r) => r.k === k && r.skill === skill).map((r) => r.chapter));
      path.push(...cs);
      return `${skill} ${cs.join(", ")}`;
    });
    console.log(`   - ${of(k)}: ${groups.join("; ")}`);
  }
}
const rest = take(map.chapters.map((ch) => ch.chapter));
path.push(...rest);
if (rest.length) console.log(`${ranked.length ? 4 : 3}. Then the rest, in book order: ${rest.join(", ")}.`);

if (evidence) {
  console.log("\n## What each chapter leaves you able to show\n");
  for (const c of path) {
    const ch = byChapter.get(c);
    if (!ch.lab.length && !ch.checks.length) continue;
    console.log(`- ${ch.chapter} ${ch.title}`);
    if (ch.lab.length) console.log(`  lab: ${ch.lab.join(", ")}`);
    if (ch.checks.length) console.log(`  checks: ${ch.checks.join("; ")}`);
    if (ch.unproven) console.log(`  not shown by the lab: ${ch.unproven}`);
  }
}
