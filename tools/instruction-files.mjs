// Reports what each instruction file puts in front of a coding agent, and when (chapter 6): its
// size in lines, words and estimated tokens, counting every file it imports, plus the problems
// nobody reading the file would notice. A file over budget; an import that doesn't resolve, or
// sits too deep to load; and a CLAUDE.md beside an AGENTS.md that it doesn't import.
//
// Usage: node tools/instruction-files.mjs [path] [--max-lines N] [--max-tokens N]
//   --max-lines defaults to 200, Claude Code's documented target for a CLAUDE.md file.
//   --max-tokens has no default. Lines are a weak budget on their own: one line can hold a
//   whole essay.
// Exit codes: 0 no problems, 1 problems (each is listed), 2 bad arguments.
//
// Rules from each tool's documentation, read on 2026-09-23:
//   Claude Code (code.claude.com/docs/en/memory): CLAUDE.md files at the root load at the start
//   of every session, and those in subdirectories load when Claude reads files there. An
//   @path import loads at launch with the file that names it, resolves relative to that file,
//   can nest four hops deep, and is ignored inside code spans and fenced code blocks. When a
//   CLAUDE.md is present, Claude Code reads AGENTS.md by default only if the CLAUDE.md imports it.
//   agents.md: an agent reads the nearest AGENTS.md in the directory tree.
// Tokens are estimated at 2.5 characters each, the average Anthropic's models page gives for its
// current tokenizer. The token-counting endpoint (chapter 2) gives an exact count.
import { existsSync, readFileSync, statSync } from "node:fs";
import { join, posix } from "node:path";

import { listFiles } from "./harness-inventory.mjs";

const MAX_HOPS = 4;
const CHARS_PER_TOKEN = 2.5;
const INSTRUCTION_FILE = /(^|\/)(AGENTS|CLAUDE|GEMINI)\.md$|^\.github\/copilot-instructions\.md$|^\.github\/instructions\/.+\.instructions\.md$/;

const number = (n) => n.toLocaleString("en-US");
const plural = (n, word) => `${number(n)} ${word}${n === 1 ? "" : "s"}`;

function fail(message) {
  console.error(message);
  process.exit(2);
}

// --- Arguments ------------------------------------------------------------------------------

let root = ".";
let maxLines = 200;
let maxTokens = null;
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--max-lines" || args[i] === "--max-tokens") {
    const value = Number(args[i + 1]);
    if (!Number.isInteger(value) || value < 1) fail(`${args[i]} needs a whole number greater than 0.`);
    if (args[i] === "--max-lines") maxLines = value;
    else maxTokens = value;
    i++;
  } else {
    root = args[i];
  }
}
if (!existsSync(root) || !statSync(root).isDirectory()) fail(`No folder at ${root}.`);

// --- Reading instruction files --------------------------------------------------------------

// Files at the root, or in the root's .claude/ or .github/ folder, load when a session starts.
const loadsAtStart = (path) => !path.includes("/") || /^\.(claude|github)\/[^/]+$/.test(path);

// The @path imports in a file's text, skipping fenced code blocks and code spans.
function importsIn(text) {
  const found = [];
  let fence = null;
  for (const line of text.split(/\r?\n/)) {
    const marker = /^ {0,3}(`{3,}|~{3,})/.exec(line);
    if (marker) {
      if (!fence) fence = marker[1][0];
      else if (marker[1][0] === fence) fence = null;
      continue;
    }
    if (fence) continue;
    const prose = line.replace(/(`+)[^`]*?\1/g, " ");
    for (const m of prose.matchAll(/(?<![\w@])@(\S+)/g)) found.push(m[1]);
  }
  return found;
}

// Windows line endings count as one character, so a file measures the same on every platform.
function measure(text) {
  const unix = text.replaceAll("\r\n", "\n");
  const lines = unix.split("\n");
  if (lines.at(-1) === "") lines.pop();
  return { lines: lines.length, words: unix.split(/\s+/).filter(Boolean).length, chars: [...unix].length };
}

// Everything that loads with one file: the file itself, then its imports, depth first. Each
// file counts once, however many times it's imported.
function load(path, problems) {
  const total = { lines: 0, words: 0, chars: 0 };
  const imported = [];
  const seen = new Set();
  const visit = (file, hops) => {
    seen.add(file);
    const text = readFileSync(join(root, file), "utf8");
    const size = measure(text);
    total.lines += size.lines;
    total.words += size.words;
    total.chars += size.chars;
    for (const target of importsIn(text)) {
      const resolved = posix.normalize(posix.join(posix.dirname(file), target.replaceAll("\\", "/")));
      // An import from the home folder, an absolute path or above the repository is outside it.
      if (target.startsWith("~") || /^([A-Za-z]:)?[\\/]/.test(target) || resolved.startsWith("../")) continue;
      const onDisk = join(root, resolved);
      if (!existsSync(onDisk) || !statSync(onDisk).isFile()) {
        problems.push(`${file} imports @${target}, which isn't a file in this repository, so nothing loads. If it's meant as text, not an import, put it in backticks.`);
        continue;
      }
      if (hops + 1 > MAX_HOPS) {
        problems.push(`${file} imports @${target}, ${MAX_HOPS + 1} hops from ${path}. Claude Code follows imports only ${MAX_HOPS} hops deep, so it never loads.`);
        continue;
      }
      if (seen.has(resolved)) continue;
      imported.push(resolved);
      visit(resolved, hops + 1);
    }
  };
  visit(path, 0);
  return { ...total, tokens: Math.round(total.chars / CHARS_PER_TOKEN), imported };
}

// --- Checking --------------------------------------------------------------------------------

const files = listFiles(root).filter((f) => INSTRUCTION_FILE.test(f)).sort();
const problems = [];
const rows = files.map((path) => ({ path, when: loadsAtStart(path) ? "session start" : "on demand", ...load(path, problems) }));

for (const row of rows) {
  const withImports = row.imported.length ? " with its imports" : "";
  if (row.lines > maxLines) {
    problems.push(`${row.path} loads ${plural(row.lines, "line")}${withImports}, over the budget of ${number(maxLines)}. Move what an agent needs only sometimes into files it reads on demand, and keep this one a map.`);
  }
  if (maxTokens !== null && row.tokens > maxTokens) {
    problems.push(`${row.path} loads about ${plural(row.tokens, "token")}${withImports}, over the budget of ${number(maxTokens)}. Look for long lines as well as many lines.`);
  }
}

// A CLAUDE.md beside an AGENTS.md hides the AGENTS.md from Claude Code unless it imports it.
for (const row of rows) {
  if (posix.basename(row.path) !== "CLAUDE.md") continue;
  let folder = posix.dirname(row.path);
  if (posix.basename(folder) === ".claude") folder = posix.dirname(folder);
  const agents = folder === "." ? "AGENTS.md" : `${folder}/AGENTS.md`;
  if (files.includes(agents) && !row.imported.includes(agents)) {
    problems.push(
      `${row.path} sits beside ${agents} but doesn't import it. With a CLAUDE.md present, Claude Code reads only the CLAUDE.md by default, ` +
        `so ${agents} reaches Claude only if it decides to open the file. Add a line that reads @AGENTS.md to ${row.path}.`,
    );
  }
}

// --- Report ----------------------------------------------------------------------------------

console.log(`Instruction files: ${root}\n`);
if (rows.length === 0) {
  console.log("None found.");
  process.exit(0);
}
const header = ["File", "Loads", "Lines", "Words", "Tokens (est.)", "Imports"];
const table = [header, ...rows.map((r) => [r.path, r.when, number(r.lines), number(r.words), number(r.tokens), r.imported.join(", ")])];
const widths = header.map((_, i) => Math.max(...table.map((row) => row[i].length)));
for (const row of table) {
  console.log(row.map((cell, i) => ([2, 3, 4].includes(i) ? cell.padStart(widths[i]) : cell.padEnd(widths[i]))).join("  ").trimEnd());
}
console.log(`\nBudget: ${number(maxLines)} lines per file, with its imports${maxTokens !== null ? `, and about ${number(maxTokens)} tokens` : ""}.`);
if (problems.length === 0) {
  console.log("No problems found.");
  process.exit(0);
}
console.log(`${plural(problems.length, "problem")}:`);
for (const problem of problems) console.log(`- ${problem}`);
process.exit(1);
