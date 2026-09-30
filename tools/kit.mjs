// The kit's checks (Appendix B): the files the path from a request to production produces, each
// checked against its skeleton or its rules, so a filled-in file that skips a part fails.
//
//   node tools/kit.mjs doc TEMPLATE FILE          a filled document against its skeleton
//   node tools/kit.mjs decisions FILE [--decided] a gap list and decisions record
//   node tools/kit.mjs skill FOLDER               a skill folder: its SKILL.md and what it references
//   node tools/kit.mjs changelog FILE             a changelog, by templates/ship/CHANGELOG-convention.md
//
// doc: every heading of the skeleton must be in the file, at the same level and in the same order
// (the file may add its own between them); every such section must say something; and no <...>
// placeholder may be left. A skeleton with "**Stages:** A, B, C" can mark a heading "[from B]": in a
// file whose "**Stage:**" line says A, that section may stay a placeholder, and it must be filled
// once the file's stage reaches B. That's a runbook's stage gate.
// decisions: every gap has an id, a question and who found it; who decides it is template, build or
// owner (or null until someone assigns it); a decision carries who made it and the day. --decided
// fails while any gap is unassigned or undecided: the gate between asking and agreeing.
// skill: the Agent Skills specification's rules for name and description (agentskills.io, read
// 2026-09-30): a name of 1 to 64 lowercase letters, digits and single hyphens, the same as its
// folder; a description of 1 to 1,024 characters. Claude Code's skills page (read the same day)
// cuts a description and when_to_use at 1,536 characters together. And the kit's own shape: the
// sections "When it applies", "Steps" (a numbered list) and "References", every reference a file
// in the folder, and SKILL.md under 500 lines, as both pages advise.
// changelog: "# Changelog", then one "## YYYY-MM-DD, what changed" heading an entry, newest first,
// each with at least one bullet.
//
// Placeholders are <...> outside code, HTML comments and <https://...> links. Every problem names
// the file, the line and what to do. Exit codes: 0 no problems, 1 problems, 2 usage or a file that
// can't be read.
import { existsSync, readFileSync, statSync } from "node:fs";
import { basename, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PLACEHOLDER = /<(?![!/]|https?:)[^<>\n]{1,200}>/g;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

function usage(message) {
  console.error(`kit: ${message}\nUsage: node tools/kit.mjs doc TEMPLATE FILE | decisions FILE [--decided] | skill FOLDER | changelog FILE`);
  process.exit(2);
}

function readText(path) {
  try {
    return readFileSync(path, "utf8").replaceAll("\r\n", "\n");
  } catch (error) {
    console.error(`kit: can't read ${path}: ${error.message}`);
    process.exit(2);
  }
}

// Lines outside fenced code, with their numbers, and inline code and comments blanked.
function prose(text) {
  const out = [];
  let fence = false;
  let comment = false;
  text.split("\n").forEach((raw, i) => {
    if (/^ {0,3}(```|~~~)/.test(raw)) {
      fence = !fence;
      return;
    }
    if (fence) return;
    let line = raw;
    if (comment) {
      const end = line.indexOf("-->");
      if (end < 0) return;
      line = line.slice(end + 3);
      comment = false;
    }
    line = line.replace(/<!--.*?-->/g, "");
    const open = line.indexOf("<!--");
    if (open >= 0) {
      line = line.slice(0, open);
      comment = true;
    }
    out.push({ n: i + 1, raw, text: line.replace(/`[^`]*`/g, "") });
  });
  return out;
}

const placeholders = (text) => [...text.matchAll(PLACEHOLDER)].map((m) => m[0]);
const heading = (text) => /^(#{1,6}) +(.+?) *$/.exec(text);
const gate = (title) => /\[from ([^\]]+)\]$/.exec(title)?.[1];
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// A template heading as a pattern: its placeholders stand for any words, such as the name in
// "# Runbook: <the service>".
function titleRegex(title) {
  let pattern = "";
  let last = 0;
  for (const m of title.matchAll(PLACEHOLDER)) {
    pattern += `${escape(title.slice(last, m.index))}.+?`;
    last = m.index + m[0].length;
  }
  return new RegExp(`^${pattern}${escape(title.slice(last))}$`);
}

// --- doc ---------------------------------------------------------------------------------------

export function checkDoc(templateText, fileText, fileName = "the file") {
  const problems = [];
  const template = prose(templateText);
  const file = prose(fileText);
  const wanted = template.map((l) => heading(l.text)).filter(Boolean).map((m) => ({ level: m[1].length, title: m[2] }));
  const stages = /^\*\*Stages:\*\* *(.+)$/m.exec(templateText)?.[1].split(",").map((s) => s.trim()) ?? [];
  const stageLine = file.find((l) => /^\*\*Stage:\*\*/.test(l.text));
  const stage = stageLine && /^\*\*Stage:\*\* *(.+?) *$/.exec(stageLine.text)?.[1];
  const reached = stages.indexOf(stage);
  if (wanted.some((w) => gate(w.title)) && stageLine && !placeholders(stageLine.text).length && reached < 0) {
    problems.push(`${fileName}:${stageLine.n}: its stage, "${stage}", isn't one of the template's stages (${stages.join(", ")}). Use one of them.`);
  }
  if (wanted.some((w) => gate(w.title)) && !stageLine) {
    problems.push(`${fileName}: has no "**Stage:**" line, so no section can wait for a later stage. Add one: ${stages.join(", ")}.`);
  }
  // Is this section switched off until a later stage?
  const waiting = (title) => {
    const from = gate(title);
    return Boolean(from) && (reached < 0 || stages.indexOf(from) > reached);
  };

  const found = file.map((l, i) => ({ i, m: heading(l.text) })).filter((h) => h.m);
  let at = 0;
  const placed = [];
  for (const [k, w] of wanted.entries()) {
    const title = titleRegex(w.title);
    const hit = found.findIndex((h, j) => j >= at && h.m[1].length === w.level && title.test(h.m[2]));
    if (hit < 0) {
      const after = placed.length ? ` after "${"#".repeat(placed.at(-1).level)} ${placed.at(-1).title}"` : "";
      problems.push(`${fileName}: the section "${"#".repeat(w.level)} ${w.title}" is missing or out of order. Add it${after}, as the template has it.`);
      continue;
    }
    placed.push({ ...w, index: found[hit].i, next: wanted[k + 1] });
    at = hit + 1;
  }
  // Each section's own lines: up to the next heading at its level or above.
  for (const p of placed) {
    const start = p.index + 1;
    let end = file.length;
    for (let k = start; k < file.length; k++) {
      const m = heading(file[k].text);
      if (m && m[1].length <= p.level) {
        end = k;
        break;
      }
    }
    const body = file.slice(start, end);
    const said = body.some((l) => l.text.trim() !== "" && !heading(l.text));
    // A heading whose own subsections come next in the template, such as a title, may say nothing.
    const nested = p.next && p.next.level > p.level;
    if (!said && !nested && !waiting(p.title)) {
      problems.push(`${fileName}:${file[p.index].n}: "${"#".repeat(p.level)} ${p.title}" says nothing. Fill it in, or write why it doesn't apply.`);
    }
  }
  // Placeholders, except in a section that waits for a later stage.
  let current = null;
  for (const l of file) {
    const m = heading(l.text);
    if (m) current = m[2];
    if (current && waiting(current)) continue;
    for (const p of placeholders(l.text)) {
      problems.push(`${fileName}:${l.n}: "${p}" is still a placeholder. Replace it with the real thing.`);
    }
  }
  return problems;
}

// --- decisions ---------------------------------------------------------------------------------

const GAP_FIELDS = ["id", "question", "found_by", "decides", "decision", "by", "on"];
const DECIDERS = ["template", "build", "owner"];

export function checkDecisions(record, fileName = "the record", { decided = false } = {}) {
  const problems = [];
  const summary = [];
  if (record === null || typeof record !== "object" || !Array.isArray(record.gaps)) {
    return { problems: [`${fileName}: needs a "gaps" list.`], summary };
  }
  const unknown = Object.keys(record).filter((k) => !["about", "brief", "gaps"].includes(k));
  if (unknown.length) problems.push(`${fileName}: unknown field(s) ${unknown.join(", ")}; a record has about, brief and gaps.`);
  for (const p of typeof record.brief === "string" ? placeholders(record.brief) : []) {
    problems.push(`${fileName}: brief "${p}" is still a placeholder. Replace it with the intake brief this record is for.`);
  }
  const text = (v) => typeof v === "string" && v.trim() !== "";
  const seen = new Set();
  const open = [];
  record.gaps.forEach((gap, i) => {
    const where = `${fileName}: gap ${typeof gap?.id === "string" ? gap.id : i + 1}`;
    if (gap === null || typeof gap !== "object") {
      problems.push(`${where}: isn't an object.`);
      return;
    }
    const extra = Object.keys(gap).filter((k) => !GAP_FIELDS.includes(k));
    const missing = GAP_FIELDS.filter((k) => !(k in gap));
    if (extra.length || missing.length) {
      const said = [extra.length ? `unknown field(s) ${extra.join(", ")}` : "", missing.length ? `missing ${missing.join(", ")}` : ""];
      problems.push(`${where}: ${said.filter(Boolean).join("; ")}. Each gap has ${GAP_FIELDS.join(", ")}, null where nothing is known yet.`);
    }
    const values = GAP_FIELDS.flatMap((k) => gap[k]).filter((v) => typeof v === "string");
    const left = values.flatMap(placeholders);
    for (const p of left) problems.push(`${where}: "${p}" is still a placeholder. Replace it, or set the field to null.`);
    if (left.length) return;
    if (typeof gap.id !== "string" || !/^G\d+$/.test(gap.id)) problems.push(`${where}: its id must be G and a number, such as G3.`);
    else if (seen.has(gap.id)) problems.push(`${where}: another gap has the same id. Ids are never reused.`);
    seen.add(gap.id);
    if (!text(gap.question)) problems.push(`${where}: needs the question the brief leaves open.`);
    if (!Array.isArray(gap.found_by) || !gap.found_by.length || !gap.found_by.every(text)) {
      problems.push(`${where}: found_by must list who or what found it, such as "spec review: reviewer-a".`);
    }
    if (gap.decides !== null && !DECIDERS.includes(gap.decides)) {
      problems.push(`${where}: decides is ${JSON.stringify(gap.decides)}; use template, build or owner, or null until someone assigns it.`);
    }
    if (gap.decision === null) {
      if (gap.by !== null || gap.on !== null) problems.push(`${where}: has who decided and when, but no decision. Write the decision, or set by and on to null.`);
      open.push(gap);
    } else if (!text(gap.decision)) {
      problems.push(`${where}: decision must be the decision in words, or null while it's open.`);
    } else {
      if (!DECIDERS.includes(gap.decides)) problems.push(`${where}: is decided, so it needs who decides it: template, build or owner.`);
      if (!text(gap.by)) problems.push(`${where}: is decided, so it needs who decided it (by).`);
      if (typeof gap.on !== "string" || !DAY.test(gap.on) || Number.isNaN(Date.parse(gap.on))) {
        problems.push(`${where}: is decided, so it needs the day it was decided (on), as YYYY-MM-DD.`);
      }
    }
  });
  const count = (kind) => record.gaps.filter((g) => g?.decides === kind).length;
  const decidedCount = record.gaps.length - open.length;
  summary.push(
    `${record.gaps.length} gap(s): ${decidedCount} decided, ${open.length} open. Who decides: ` +
      `${DECIDERS.map((k) => `${k} ${count(k)}`).join(", ")}, not assigned ${record.gaps.filter((g) => g?.decides === null).length}.`,
  );
  for (const gap of open) summary.push(`  open  ${gap.id}  ${gap.decides ?? "not assigned"}: ${gap.question}`);
  if (decided && open.length) {
    problems.push(`${fileName}: ${open.length} gap(s) still open (${open.map((g) => g.id).join(", ")}). Each needs a decision, who made it and when, before the spec is agreed.`);
  }
  return { problems, summary };
}

// --- skill -------------------------------------------------------------------------------------

export function checkSkill(folder) {
  const problems = [];
  const path = join(folder, "SKILL.md");
  const file = path.replaceAll("\\", "/");
  if (!existsSync(path)) return [`${folder}: has no SKILL.md. A skill is a folder whose SKILL.md says what it does.`];
  const text = readText(path);
  const lines = text.split("\n");
  if (lines[0] !== "---") return [`${file}:1: must start with "---" and its frontmatter (name, description).`];
  const close = lines.indexOf("---", 1);
  if (close < 0) return [`${file}: its frontmatter never closes with "---".`];
  const fields = {};
  for (const [i, line] of lines.slice(1, close).entries()) {
    const m = /^([A-Za-z][\w-]*): *(.*)$/.exec(line);
    if (m) fields[m[1]] = m[2].replace(/^(["'])(.*)\1$/, "$2");
    else if (line.trim() && !/^\s/.test(line)) problems.push(`${file}:${i + 2}: isn't a "field: value" line.`);
  }
  const name = fields.name ?? "";
  const folderName = basename(resolve(folder));
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(name) || name.length > 64) {
    problems.push(`${file}: name "${name}" must be 1 to 64 lowercase letters, digits and single hyphens, not starting or ending with one.`);
  } else if (name !== folderName) {
    problems.push(`${file}: name "${name}" must be the folder's name, "${folderName}".`);
  }
  const description = fields.description ?? "";
  if (!description.trim() || description.length > 1024) {
    problems.push(`${file}: description must be 1 to 1,024 characters that say what the skill does and when to use it.`);
  }
  if ((description + (fields.when_to_use ?? "")).length > 1536) {
    problems.push(`${file}: description and when_to_use run past 1,536 characters together, where Claude Code cuts them. Shorten them.`);
  }
  if (lines.length > 500) problems.push(`${file}: is ${lines.length} lines. Keep it under 500, and move detail into a referenced file.`);
  const body = prose(lines.slice(close + 1).join("\n")).map((l) => ({ ...l, n: l.n + close + 1 }));
  const sections = {};
  let current = null;
  for (const l of body) {
    const m = heading(l.text);
    if (m && m[1].length === 2) current = sections[m[2]] = [];
    else if (current) current.push(l);
  }
  for (const title of ["When it applies", "Steps", "References"]) {
    if (!sections[title]) problems.push(`${file}: needs a "## ${title}" section.`);
  }
  if (sections.Steps && !sections.Steps.some((l) => /^\d+\. \S/.test(l.text))) {
    problems.push(`${file}: "## Steps" needs a numbered list, one step a line, such as "1. Run the checks."`);
  }
  if (sections["When it applies"] && !sections["When it applies"].some((l) => l.text.trim())) {
    problems.push(`${file}: "## When it applies" says nothing. Say when to use the skill, and when not to.`);
  }
  const links = (sections.References ?? []).flatMap((l) => [...l.raw.matchAll(/\]\(([^)]+)\)/g)].map((m) => ({ l, target: m[1].trim() })));
  if (sections.References && !links.length) problems.push(`${file}: "## References" links to no file. Link each file the skill uses.`);
  for (const { l, target } of links) {
    const local = normalize(target);
    // A link still to be filled in is reported as a placeholder, below; so is a web address.
    if (/^[a-z][a-z0-9+.-]*:/i.test(target) || placeholders(target).join("") === target) continue;
    if (local.startsWith("..") || resolve(folder, local) === resolve(file) || local.split(/[\\/]/).length > 2) {
      problems.push(`${file}:${l.n}: ${target} must be a file in the skill's folder, one level deep at most.`);
    } else if (!existsSync(join(folder, local)) || !statSync(join(folder, local)).isFile()) {
      problems.push(`${file}:${l.n}: ${target} isn't in the skill's folder. Add it, or fix the link.`);
    }
  }
  for (const l of [...lines.slice(0, close + 1).map((raw, i) => ({ n: i + 1, text: raw })), ...body]) {
    for (const p of placeholders(l.text)) problems.push(`${file}:${l.n}: "${p}" is still a placeholder. Replace it with the real thing.`);
  }
  return problems;
}

// --- changelog ---------------------------------------------------------------------------------

export function checkChangelog(text, fileName = "CHANGELOG.md") {
  const problems = [];
  const lines = prose(text);
  if (lines[0]?.text !== "# Changelog") problems.push(`${fileName}:1: must start with "# Changelog".`);
  const entries = [];
  for (const l of lines) {
    const m = heading(l.text);
    if (!m || m[1].length === 1) {
      if (entries.length && /^- \S/.test(l.text)) entries.at(-1).bullets++;
      continue;
    }
    if (m[1].length > 2) continue;
    const dated = /^(\d{4}-\d{2}-\d{2})(, \S.*)?$/.exec(m[2]);
    if (!dated || Number.isNaN(Date.parse(dated[1]))) {
      problems.push(`${fileName}:${l.n}: "${l.text}" must start with the day, as "## YYYY-MM-DD, what changed".`);
      entries.push({ n: l.n, day: null, bullets: 0 });
      continue;
    }
    const before = entries.findLast((e) => e.day);
    if (before && dated[1] > before.day) {
      problems.push(`${fileName}:${l.n}: ${dated[1]} comes after ${before.day} (line ${before.n}), but entries go newest first. Move it up.`);
    }
    entries.push({ n: l.n, day: dated[1], bullets: 0 });
  }
  if (!entries.length) problems.push(`${fileName}: has no entries. Add "## YYYY-MM-DD, what changed" with a bullet for each change.`);
  for (const e of entries) {
    if (e.bullets === 0) problems.push(`${fileName}:${e.n}: the entry has no bullets. Say what changed, and why, in "- " lines.`);
  }
  return { problems, entries: entries.length };
}

// --- the command -------------------------------------------------------------------------------

function report(title, problems, extra = []) {
  console.log(`${title}\n`);
  for (const line of extra) console.log(line);
  if (extra.length) console.log("");
  if (!problems.length) {
    console.log("No problems found.");
    process.exit(0);
  }
  console.log(`${problems.length} problem(s):`);
  for (const p of problems) console.log(`- ${p}`);
  process.exit(1);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [what, ...args] = process.argv.slice(2);
  if (what === "doc") {
    if (args.length !== 2) usage("doc needs a TEMPLATE and a FILE.");
    const [template, file] = args;
    report(`Kit document: ${file}, against ${template}`, checkDoc(readText(template), readText(file), file));
  } else if (what === "decisions") {
    const file = args.find((a) => !a.startsWith("--"));
    if (!file || args.some((a) => a.startsWith("--") && a !== "--decided")) usage("decisions needs a FILE, and takes --decided.");
    let record;
    try {
      record = JSON.parse(readText(file));
    } catch (error) {
      report(`Gap list: ${file}`, [`${file} isn't valid JSON: ${error.message}`]);
    }
    const { problems, summary } = checkDecisions(record, file, { decided: args.includes("--decided") });
    report(`Gap list: ${file}`, problems, summary);
  } else if (what === "skill") {
    if (args.length !== 1) usage("skill needs a FOLDER.");
    report(`Skill: ${args[0]}`, checkSkill(args[0]));
  } else if (what === "changelog") {
    if (args.length !== 1) usage("changelog needs a FILE.");
    const { problems, entries } = checkChangelog(readText(args[0]), args[0]);
    report(`Changelog: ${args[0]}`, problems, [`${entries} entries.`]);
  } else {
    usage(what ? `${what} isn't a check.` : "say which check to run.");
  }
}
