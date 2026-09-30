// Measures what a project claims, and writes the proof page (Prove, Appendix B):
// node tools/claims.mjs CLAIMS.json [--root DIR] [--out PAGE.md]
//
// A claims file lists sentences someone might repeat about the project, each with the command that
// measures it and what the command must do for the claim to hold: exit with a given code and,
// optionally, print a given piece of text. This runs every command, from the repository's root
// (--root, by default the folder this runs in), and writes one Markdown page: each claim, pass, fail
// or unknown, and when it was measured, at which commit. A claim is unknown when nothing measured
// it: no command, a command that couldn't start or wasn't found, or one that ran out of time.
// Unknown isn't a pass, so the run fails on a fail or an unknown, and says which. The time limit
// stops the shell that runs a command; a program that command started may run on a little longer.
//
// The page goes where --out says, or where the claims file's "proof" field says, from its own
// folder. A claims file that's malformed, or still has a <...> placeholder, is refused, and no page
// is written. Exit codes: 0 every claim holds, 1 a claim failed or is unknown, or the file was
// refused, 2 usage or a file that can't be read.
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FIELDS = ["id", "claim", "command", "expect", "timeout_seconds"];
const PLACEHOLDER = /<(?![!/]|https?:)[^<>\n]{1,200}>/g;
const DEFAULT_TIMEOUT = 300;
// A command the shell couldn't find: sh and bash exit 127; Windows' cmd exits 1 (or 9009 inside a
// batch file) and says so on stderr, in English on an English system.
const NOT_FOUND = new Set([127, 9009]);
const notFound = (status, output) =>
  NOT_FOUND.has(status) || (process.platform === "win32" && status === 1 && /is not recognized as an internal or external command/.test(output));

export function problems(file, name = "the claims file") {
  const found = [];
  if (file === null || typeof file !== "object" || !Array.isArray(file.claims)) return [`${name}: needs a "claims" list.`];
  const extra = Object.keys(file).filter((k) => !["about", "proof", "claims"].includes(k));
  if (extra.length) found.push(`${name}: unknown field(s) ${extra.join(", ")}; a claims file has about, proof and claims.`);
  if (typeof file.proof !== "string" || !file.proof.endsWith(".md")) found.push(`${name}: "proof" must name the page to write, a .md file.`);
  const seen = new Set();
  file.claims.forEach((c, i) => {
    const where = `${name}: ${typeof c?.id === "string" && c.id ? c.id : `claim ${i + 1}`}`;
    if (c === null || typeof c !== "object") {
      found.push(`${where}: isn't an object.`);
      return;
    }
    const unknown = Object.keys(c).filter((k) => !FIELDS.includes(k));
    const missing = ["id", "claim", "command", "expect"].filter((k) => !(k in c));
    if (unknown.length || missing.length) {
      const said = [unknown.length ? `unknown field(s) ${unknown.join(", ")}` : "", missing.length ? `missing ${missing.join(", ")}` : ""];
      found.push(`${where}: ${said.filter(Boolean).join("; ")}. A claim has id, claim, command and expect, and may have timeout_seconds.`);
    }
    const texts = [c.id, c.claim, c.command, c.expect?.output].filter((v) => typeof v === "string");
    const left = texts.flatMap((t) => [...t.matchAll(PLACEHOLDER)].map((m) => m[0]));
    for (const p of left) found.push(`${where}: "${p}" is still a placeholder. Replace it with the real thing.`);
    if (left.length) return;
    if (typeof c.id !== "string" || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(c.id)) found.push(`${where}: its id must be lowercase words joined by hyphens.`);
    else if (seen.has(c.id)) found.push(`${where}: another claim has the same id.`);
    seen.add(c.id);
    if (typeof c.claim !== "string" || !c.claim.trim()) found.push(`${where}: needs the sentence it claims.`);
    if (c.command !== null && (typeof c.command !== "string" || !c.command.trim())) {
      found.push(`${where}: command must be the command that measures it, or null when nothing can yet.`);
    }
    const e = c.expect;
    if (e === null || typeof e !== "object" || !Number.isInteger(e.exit) || Object.keys(e).some((k) => !["exit", "output"].includes(k))) {
      found.push(`${where}: expect must be { "exit": CODE }, with "output": TEXT if the output must contain it.`);
    } else if ("output" in e && (typeof e.output !== "string" || !e.output)) {
      found.push(`${where}: expect.output must be the text the output must contain.`);
    }
    if ("timeout_seconds" in c && !(Number.isInteger(c.timeout_seconds) && c.timeout_seconds > 0)) {
      found.push(`${where}: timeout_seconds must be a whole number of seconds.`);
    }
  });
  return found;
}

const tail = (text, n = 12) => text.trimEnd().split(/\r?\n/).slice(-n).join("\n");

// One claim, measured: its result, why, when, and the end of what the command printed.
export function measure(claim, root) {
  const at = new Date();
  if (claim.command === null) return { result: "unknown", why: "no command measures it yet", at, output: "" };
  const seconds = claim.timeout_seconds ?? DEFAULT_TIMEOUT;
  const run = spawnSync(claim.command, { cwd: root, shell: true, encoding: "utf8", timeout: seconds * 1000 });
  const output = `${run.stdout ?? ""}${run.stderr ?? ""}`;
  if (run.error?.code === "ETIMEDOUT" || (run.status === null && run.signal)) {
    return { result: "unknown", why: `it didn't finish within ${seconds} seconds`, at, output };
  }
  if (run.error || run.status === null) return { result: "unknown", why: `it couldn't run: ${run.error?.message ?? "no exit code"}`, at, output };
  if (notFound(run.status, output) && claim.expect.exit !== run.status) {
    return { result: "unknown", why: `its program wasn't found (exit ${run.status})`, at, output };
  }
  if (run.status !== claim.expect.exit) return { result: "fail", why: `it exited ${run.status}, not ${claim.expect.exit}`, at, output };
  if (claim.expect.output && !output.includes(claim.expect.output)) {
    return { result: "fail", why: `its output doesn't contain ${JSON.stringify(claim.expect.output)}`, at, output };
  }
  return { result: "pass", why: "", at, output };
}

const stamp = (date) => `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;

// The commit the claims were measured at, and whether the files differed from it.
function commit(root) {
  const head = spawnSync("git", ["rev-parse", "--short=12", "HEAD"], { cwd: root, encoding: "utf8" });
  if (head.status !== 0) return "no commit (not a git repository)";
  const dirty = spawnSync("git", ["status", "--porcelain", "--untracked-files=no"], { cwd: root, encoding: "utf8" }).stdout.trim();
  return `commit ${head.stdout.trim()}${dirty ? ", with uncommitted changes" : ""}`;
}

export function page(file, measured, claimsName, where) {
  const cell = (text) => String(text).replaceAll("|", "\\|").replaceAll("\n", " ");
  const count = (r) => measured.filter((m) => m.result === r).length;
  const lines = [
    "# Proof",
    "",
    `<!-- Generated by node tools/claims.mjs from ${claimsName}. Don't edit it by hand: run the script again. -->`,
    "",
    `Measured ${measured.length ? stamp(measured[0].at) : "never"}, at ${where}. ${measured.length} claim(s): ` +
      `${count("pass")} pass, ${count("fail")} fail, ${count("unknown")} unknown.`,
    "",
    "| Claim | Result | Measured | Command |",
    "|---|---|---|---|",
    ...file.claims.map((c, i) => `| ${cell(c.claim)} | ${measured[i].result} | ${stamp(measured[i].at)} | ${c.command === null ? "none" : `\`${cell(c.command)}\``} |`),
  ];
  const open = file.claims.map((c, i) => ({ c, m: measured[i] })).filter(({ m }) => m.result !== "pass");
  if (open.length) {
    lines.push("", "## What failed, and what's unknown");
    for (const { c, m } of open) {
      lines.push("", `### ${c.id}: ${m.result}`, "", `${c.claim} Not shown to hold: ${m.why}.`);
      if (m.output.trim()) lines.push("", "```", tail(m.output), "```");
    }
  }
  return `${lines.join("\n")}\n`;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const option = (name) => {
    const at = args.indexOf(name);
    return at >= 0 ? args[at + 1] : undefined;
  };
  const root = option("--root") ?? ".";
  const files = args.filter((a, i) => !a.startsWith("--") && !["--root", "--out"].includes(args[i - 1]));
  if (files.length !== 1 || args.some((a) => a.startsWith("--") && !["--root", "--out"].includes(a))) {
    console.error("Usage: node tools/claims.mjs CLAIMS.json [--root DIR] [--out PAGE.md]");
    process.exit(2);
  }
  let file;
  try {
    file = JSON.parse(readFileSync(files[0], "utf8"));
  } catch (error) {
    console.error(`claims: ${files[0]} can't be read as JSON: ${error.message}`);
    process.exit(2);
  }
  const found = problems(file, files[0]);
  if (found.length) {
    console.log(`Claims: ${files[0]}\n\n${found.length} problem(s), so nothing was measured and no page was written:`);
    for (const p of found) console.log(`- ${p}`);
    process.exit(1);
  }
  const out = option("--out") ?? join(dirname(files[0]), file.proof);
  const measured = file.claims.map((c) => measure(c, root));
  writeFileSync(out, page(file, measured, basename(files[0]), commit(root)));
  console.log(`Claims: ${files[0]}\n`);
  file.claims.forEach((c, i) => {
    const m = measured[i];
    console.log(`${m.result.toUpperCase().padEnd(7)}  ${c.id}${m.why ? `: ${m.why}` : ""}`);
  });
  const held = measured.filter((m) => m.result === "pass").length;
  console.log(`\n${held} of ${measured.length} claim(s) hold. Wrote ${out.replaceAll("\\", "/")}.`);
  process.exit(held === measured.length ? 0 : 1);
}
