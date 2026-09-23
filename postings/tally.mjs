// Counts a coded sample of job postings, so no figure is ever tallied by hand.
// Usage: node postings/tally.mjs <postings.json>
// Exit codes: 0 counted, 1 the data has problems (each one is listed), 2 usage.
import { readFileSync } from "node:fs";

const TYPES = ["infrastructure", "enablement", "product-agents", "coding-agents", "applied"];
const SIGNALS = [
  "agents", "codingAgents", "mcp", "retrieval", "evaluation", "guardrails",
  "aiObservability", "costControl", "humanApproval", "security", "servingOrTraining", "kubernetes",
];
const LANGUAGES = ["python", "typescriptOrJavascript", "go", "java", "dotnet"];

const file = process.argv[2];
if (!file) {
  console.error("usage: node postings/tally.mjs <postings.json>");
  process.exit(2);
}
const data = JSON.parse(readFileSync(file, "utf8"));

// Check everything before counting anything. A typo must stop the run, not quietly count as "no".
// Each message names the posting, the field and what to do, so the fix is in the error itself.
function problemsIn(data) {
  const problems = [];
  if (typeof data.sample?.pulled !== "string") problems.push('sample.pulled is missing. Set it to the date you read the postings.');
  if (!Array.isArray(data.postings)) return [...problems, "postings is missing. It must be a list of coded postings."];
  if (!Array.isArray(data.excluded)) problems.push("excluded is missing. Use [] if you excluded nothing.");
  const codebook = data.codebook ?? {};
  const seen = new Set();
  data.postings.forEach((p, i) => {
    const who = typeof p.id === "string" && p.id ? p.id : `posting ${i + 1}`;
    if (who !== p.id) problems.push(`${who}: id is missing. Give every posting a short unique id such as P01.`);
    else if (seen.has(p.id)) problems.push(`${who}: id is used twice. Give every posting its own id.`);
    seen.add(p.id);
    if (!TYPES.includes(p.type)) problems.push(`${who}: type is ${JSON.stringify(p.type)}. Use one of: ${TYPES.join(", ")}.`);
    if (p.alsoType != null && (!TYPES.includes(p.alsoType) || p.alsoType === p.type)) {
      problems.push(`${who}: alsoType is ${JSON.stringify(p.alsoType)}. Use null or a type other than the primary one.`);
    }
    for (const key of [...SIGNALS, ...LANGUAGES]) {
      if (typeof p[key] === "boolean") continue;
      const found = key in p ? `is ${JSON.stringify(p[key])}` : "is missing";
      const hint = codebook[key] ?? (LANGUAGES.includes(key) ? codebook.languages : undefined);
      problems.push(`${who}: "${key}" ${found}. Set it to true or false.${hint ? ` Codebook: ${hint}` : ""}`);
    }
    if (!Array.isArray(p.codingAgentsNamed)) problems.push(`${who}: codingAgentsNamed must be a list. Use [] if none are named.`);
    if (p.yearsRequired != null && typeof p.yearsRequired !== "number") problems.push(`${who}: yearsRequired must be a number or null.`);
    if (p.degreeRequired != null && typeof p.degreeRequired !== "boolean") problems.push(`${who}: degreeRequired must be true, false or null.`);
    for (const key of ["source", "employment", "arrangement"]) {
      if (typeof p[key] !== "string") problems.push(`${who}: ${key} must be text. Use "unknown" if the posting does not say.`);
    }
  });
  return problems;
}

const problems = problemsIn(data);
if (problems.length) {
  console.error(`${file}: ${problems.length} problem(s). Nothing was counted.`);
  for (const line of problems) console.error(`- ${line}`);
  process.exit(1);
}

const posts = data.postings;
const n = posts.length;
const pct = (k) => `${Math.round((100 * k) / n)}%`;
const countWhere = (pred) => posts.filter(pred).length;
const tally = (values) => {
  const m = new Map();
  for (const v of values) m.set(v, (m.get(v) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
};

console.log(`# Tally of ${file}\n`);
console.log(`Included: ${n}. Excluded: ${data.excluded.length}. Pulled: ${data.sample.pulled}.\n`);

console.log("## Primary type\n\n| Type | Count | Share |\n|---|---|---|");
for (const [t, k] of tally(posts.map((p) => p.type))) console.log(`| ${t} | ${k} | ${pct(k)} |`);
const also = posts.filter((p) => p.alsoType);
console.log(`\nSecond type recorded on ${also.length}: ${also.map((p) => `${p.id} ${p.alsoType}`).join(", ") || "none"}.\n`);

console.log("## Signals\n\n| Signal | Count | Share |\n|---|---|---|");
for (const [s, k] of SIGNALS.map((s) => [s, countWhere((p) => p[s])]).sort((a, b) => b[1] - a[1])) {
  console.log(`| ${s} | ${k} | ${pct(k)} |`);
}

console.log("\n## Languages named\n\n| Language | Count | Share |\n|---|---|---|");
for (const [l, k] of LANGUAGES.map((l) => [l, countWhere((p) => p[l])]).sort((a, b) => b[1] - a[1])) {
  console.log(`| ${l} | ${k} | ${pct(k)} |`);
}

console.log("\n## Coding agents named\n");
const named = tally(posts.flatMap((p) => p.codingAgentsNamed));
console.log(named.length ? named.map(([name, k]) => `- ${name}: ${k}`).join("\n") : "- none");

console.log("\n## Signals by primary type\n");
const types = tally(posts.map((p) => p.type)).map(([t]) => t);
console.log(`| Signal | ${types.join(" | ")} |\n|---|${types.map(() => "---").join("|")}|`);
for (const s of SIGNALS) {
  const cells = types.map((t) => {
    const group = posts.filter((p) => p.type === t);
    return `${group.filter((p) => p[s]).length}/${group.length}`;
  });
  console.log(`| ${s} | ${cells.join(" | ")} |`);
}

console.log("\n## Signals and languages by source\n");
const sources = tally(posts.map((p) => p.source)).map(([s]) => s);
console.log(`| Signal | ${sources.join(" | ")} |\n|---|${sources.map(() => "---").join("|")}|`);
for (const s of [...SIGNALS, ...LANGUAGES]) {
  const cells = sources.map((src) => {
    const group = posts.filter((p) => p.source === src);
    return `${group.filter((p) => p[s]).length}/${group.length}`;
  });
  console.log(`| ${s} | ${cells.join(" | ")} |`);
}

const years = posts.map((p) => p.yearsRequired).filter((y) => typeof y === "number").sort((a, b) => a - b);
const median = years.length
  ? years.length % 2
    ? years[(years.length - 1) / 2]
    : (years[years.length / 2 - 1] + years[years.length / 2]) / 2
  : null;
console.log("\n## Requirements\n");
console.log(`- Years of experience stated on ${years.length} of ${n}: min ${years[0] ?? "n/a"}, median ${median ?? "n/a"}, max ${years.at(-1) ?? "n/a"}.`);
console.log(`- Degree explicitly required on ${countWhere((p) => p.degreeRequired === true)} of ${n}.`);
console.log(`- Employment: ${tally(posts.map((p) => p.employment)).map(([e, k]) => `${e} ${k}`).join(", ")}.`);
console.log(`- Arrangement: ${tally(posts.map((p) => p.arrangement)).map(([a, k]) => `${a} ${k}`).join(", ")}.`);
