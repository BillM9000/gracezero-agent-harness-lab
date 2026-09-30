// Counts a coded sample of job postings, so no figure is ever tallied by hand.
// Usage: node postings/tally.mjs <postings.json>
// Exit codes: 0 counted, 1 the data has problems (each one is listed), 2 usage.
import { readFileSync } from "node:fs";

const TYPES = ["infrastructure", "enablement", "product-agents", "coding-agents", "applied"];
const SIGNALS = [
  "agents", "codingAgents", "mcp", "retrieval", "evaluation", "guardrails",
  "aiObservability", "costControl", "humanApproval", "security", "servingOrTraining", "kubernetes",
  "gateway",
];
const LANGUAGES = ["python", "typescriptOrJavascript", "go", "java", "dotnet"];
// Fields that may be null but must be there: a missing or misspelled one would count as null.
const NULLABLE = {
  alsoType: "null, or a type other than the primary one",
  yearsRequired: "a number, or null if the posting does not say",
  degreeRequired: "true, false, or null if the posting does not say",
};
// When and how each posting was coded, as the codebook defines them: readOn on every posting,
// screenedOn on every exclusion record, publicWorkAsked on every posting with "architect" in its
// title, and gatewayBasis wherever a sample records where its gateway codes came from.
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const GATEWAY_BASIS = ["text", "reread", "note"];
const PUBLIC_WORK = ["required", "asked", "preferred", "none", "not re-read"];
const isArchitect = (p) => /architect/i.test(p.title);
const isDate = (value) => typeof value === "string" && DATE.test(value);

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
    for (const [key, allowed] of Object.entries(NULLABLE)) {
      if (!(key in p)) problems.push(`${who}: "${key}" is missing. Set it to ${allowed}.`);
    }
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
    if (!isDate(p.readOn)) {
      const found = "readOn" in p ? `is ${JSON.stringify(p.readOn)}` : "is missing";
      problems.push(`${who}: "readOn" ${found}. Set it to the day you read the posting in full, as YYYY-MM-DD.`);
    }
    if ("gatewayBasis" in p && !GATEWAY_BASIS.includes(p.gatewayBasis)) {
      problems.push(`${who}: "gatewayBasis" is ${JSON.stringify(p.gatewayBasis)}. Use one of: ${GATEWAY_BASIS.join(", ")}, or leave it out.`);
    }
    if ((isArchitect(p) || "publicWorkAsked" in p) && !PUBLIC_WORK.includes(p.publicWorkAsked)) {
      const found = "publicWorkAsked" in p ? `is ${JSON.stringify(p.publicWorkAsked)}` : "is missing, and the title names an architect";
      problems.push(`${who}: "publicWorkAsked" ${found}. Use one of: ${PUBLIC_WORK.join(", ")}.`);
    }
  });
  (Array.isArray(data.excluded) ? data.excluded : []).forEach((e, i) => {
    if (isDate(e?.screenedOn)) return;
    const found = e !== null && typeof e === "object" && "screenedOn" in e ? `is ${JSON.stringify(e.screenedOn)}` : "is missing";
    problems.push(`excluded record ${i + 1}: "screenedOn" ${found}. Set it to the day you screened the posting out, as YYYY-MM-DD.`);
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
const pct = (k, of = n) => (of ? `${Math.round((100 * k) / of)}%` : "n/a");
const countWhere = (pred, list = posts) => list.filter(pred).length;
const tally = (values) => {
  const m = new Map();
  for (const v of values) m.set(v, (m.get(v) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
};
const byDate = (values) => [...tally(values)].sort((a, b) => a[0].localeCompare(b[0]));
const years = (list) => {
  const y = list.map((p) => p.yearsRequired).filter((v) => typeof v === "number").sort((a, b) => a - b);
  const median = y.length ? (y.length % 2 ? y[(y.length - 1) / 2] : (y[y.length / 2 - 1] + y[y.length / 2]) / 2) : null;
  return `stated on ${y.length} of ${list.length}: min ${y[0] ?? "n/a"}, median ${median ?? "n/a"}, max ${y.at(-1) ?? "n/a"}`;
};
const dated = (pairs) => pairs.map(([d, k]) => `${d}: ${k}`).join(", ") || "none";

console.log(`# Tally of ${file}\n`);
console.log(`Included: ${n}. Excluded: ${data.excluded.length}. Pulled: ${data.sample.pulled}.\n`);
const reads = byDate(posts.map((p) => p.readOn));
const firstRead = reads[0]?.[0];
const lastRead = reads.at(-1)?.[0];
console.log(`Read on: ${reads.length ? `${firstRead} to ${lastRead} (${dated(reads)})` : "none"}.`);
console.log(`Exclusion records by screening date: ${dated(byDate(data.excluded.map((e) => e.screenedOn)))}.\n`);

console.log("## Primary type\n\n| Type | Count | Share |\n|---|---|---|");
for (const [t, k] of tally(posts.map((p) => p.type))) console.log(`| ${t} | ${k} | ${pct(k)} |`);
const also = posts.filter((p) => p.alsoType);
console.log(`\nSecond type recorded on ${also.length}: ${also.map((p) => `${p.id} ${p.alsoType}`).join(", ") || "none"}.`);
const types = tally(posts.map((p) => p.type)).map(([t]) => t);
console.log(`\nPrimary or second type: ${types.map((t) => `${t} ${countWhere((p) => p.type === t || p.alsoType === t)}`).join(", ")}.\n`);

console.log("## Signals\n\n| Signal | Count | Share |\n|---|---|---|");
for (const [s, k] of SIGNALS.map((s) => [s, countWhere((p) => p[s])]).sort((a, b) => b[1] - a[1])) {
  console.log(`| ${s} | ${k} | ${pct(k)} |`);
}
// Where the gateway codes came from, for a sample that records it. A posting coded "reread" was
// read again when the sample was last extended, which is its latest read date.
const basis = (b) => posts.filter((p) => p.gatewayBasis === b);
const ids = (list) => list.map((p) => p.id).join(", ") || "none";
if (posts.some((p) => "gatewayBasis" in p)) {
  console.log(`\nGateway coded from: the posting's text when first read ${basis("text").length}; the text read again on ${lastRead} ${basis("reread").length} (${ids(basis("reread"))}); the posting's note, the text no longer reachable, ${basis("note").length} (${ids(basis("note"))}).`);
} else {
  console.log("");
}
console.log(`Gateway true on: ${posts.filter((p) => p.gateway).map((p) => `${p.id}${p.gatewayBasis ? ` (${p.gatewayBasis})` : ""}`).join(", ") || "none"}.`);

console.log("\n## Languages named\n\n| Language | Count | Share |\n|---|---|---|");
for (const [l, k] of LANGUAGES.map((l) => [l, countWhere((p) => p[l])]).sort((a, b) => b[1] - a[1])) {
  console.log(`| ${l} | ${k} | ${pct(k)} |`);
}

console.log("\n## Coding agents named\n");
const named = tally(posts.flatMap((p) => p.codingAgentsNamed));
console.log(named.length ? named.map(([name, k]) => `- ${name}: ${k}`).join("\n") : "- none");
// Families group the names as postings wrote them; a posting counts once per family.
const FAMILIES = [
  ["any form of Copilot", /copilot/i],
  ["Claude Code", /^claude code$/i],
  ["Claude Code or plain Claude", /^claude( code)?$/i],
  ["any form of Codex", /codex/i],
];
console.log(`\nBy family, postings naming: ${FAMILIES.map(([label, re]) => `${label} ${countWhere((p) => p.codingAgentsNamed.some((x) => re.test(x)))}`).join("; ")}.`);

console.log("\n## Signals by primary type\n");
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

console.log("\n## By read date\n");
const dates = reads.map(([d]) => d);
const onDate = (d) => posts.filter((p) => p.readOn === d);
console.log(`| Primary type | ${dates.join(" | ")} |\n|---|${dates.map(() => "---").join("|")}|`);
for (const t of types) console.log(`| ${t} | ${dates.map((d) => `${countWhere((p) => p.type === t, onDate(d))}/${onDate(d).length}`).join(" | ")} |`);
console.log(`\n| Signal | ${dates.join(" | ")} |\n|---|${dates.map(() => "---").join("|")}|`);
for (const s of [...SIGNALS, ...LANGUAGES]) {
  const cells = dates.map((d) => `${countWhere((p) => p[s], onDate(d))}/${onDate(d).length}`);
  console.log(`| ${s} | ${cells.join(" | ")} |`);
}
console.log("");
for (const d of dates) {
  console.log(`- Read ${d}: years of experience ${years(onDate(d))}; degree explicitly required on ${countWhere((p) => p.degreeRequired === true, onDate(d))} of ${onDate(d).length}.`);
}

// Postings with "architect" in the title against the rest, so the two can be compared.
const arch = posts.filter(isArchitect);
const other = posts.filter((p) => !isArchitect(p));
console.log("\n## Architect titles\n");
if (!arch.length) {
  console.log(`Titles containing "architect": 0 of ${n}.`);
} else {
  console.log(`Titles containing "architect": ${arch.length} of ${n} (read ${firstRead}: ${countWhere((p) => p.readOn === firstRead, arch)}; later: ${countWhere((p) => p.readOn !== firstRead, arch)}).\n`);
  console.log(arch.map((p) => `- ${p.id} ${p.type}${p.alsoType ? ` + ${p.alsoType}` : ""}: ${p.title}`).join("\n"));
  console.log(`\n| Type | Architect (${arch.length}) | Other (${other.length}) |\n|---|---|---|`);
  for (const t of types) console.log(`| ${t} | ${countWhere((p) => p.type === t, arch)} | ${countWhere((p) => p.type === t, other)} |`);
  console.log(`\n| Signal | Architect (${arch.length}) | Share | Other (${other.length}) | Share |\n|---|---|---|---|---|`);
  for (const s of [...SIGNALS, ...LANGUAGES]) {
    const a = countWhere((p) => p[s], arch);
    const o = countWhere((p) => p[s], other);
    console.log(`| ${s} | ${a} | ${pct(a, arch.length)} | ${o} | ${pct(o, other.length)} |`);
  }
  console.log(`\n- Years of experience, architect titles: ${years(arch)}.`);
  console.log(`- Years of experience, other titles: ${years(other)}.`);
  console.log(`- Degree explicitly required: architect ${countWhere((p) => p.degreeRequired === true, arch)} of ${arch.length}; other ${countWhere((p) => p.degreeRequired === true, other)} of ${other.length}.`);
  console.log(`- Employment, architect titles: ${tally(arch.map((p) => p.employment)).map(([e, k]) => `${e} ${k}`).join(", ")}.`);
  console.log(`- Pay stated on ${countWhere((p) => p.pay, arch)} of ${arch.length} architect postings:`);
  for (const p of arch) console.log(`  - ${p.id}: ${p.pay ?? "not stated"}`);
  console.log("- Public body of work asked for in so many words:");
  for (const level of PUBLIC_WORK) {
    const asked = arch.filter((p) => p.publicWorkAsked === level).map((p) => p.id);
    console.log(`  - ${level}: ${asked.length}${asked.length ? ` (${asked.join(", ")})` : ""}`);
  }
}

console.log("\n## Requirements\n");
console.log(`- Years of experience ${years(posts)}.`);
console.log(`- Degree explicitly required on ${countWhere((p) => p.degreeRequired === true)} of ${n}.`);
console.log(`- Employment: ${tally(posts.map((p) => p.employment)).map(([e, k]) => `${e} ${k}`).join(", ")}.`);
console.log(`- Arrangement: ${tally(posts.map((p) => p.arrangement)).map(([a, k]) => `${a} ${k}`).join(", ")}.`);
