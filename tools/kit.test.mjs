// Tests for tools/kit.mjs (Appendix B): each of its checks passes what the kit's rules allow, and
// fails each planted break with a message that says what to do.
// Run: node --test tools/kit.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

import { checkChangelog, checkDecisions, checkDoc, checkSkill } from "./kit.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const KIT = join(ROOT, "tools", "kit.mjs");
const base = mkdtempSync(join(tmpdir(), "kit-"));
after(() => rmSync(base, { recursive: true, force: true }));
let n = 0;
function folder(files) {
  const root = join(base, `case-${++n}`);
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  return root;
}
const kit = (...args) => {
  const run = spawnSync(process.execPath, [KIT, ...args], { encoding: "utf8" });
  return { status: run.status, output: `${run.stdout}${run.stderr}` };
};

// --- doc ---------------------------------------------------------------------------------------

const TEMPLATE = [
  "# Plan: <the thing>",
  "",
  "<!-- How to fill it in. -->",
  "",
  "**Stages:** Alpha, Beta, Production",
  "**Stage:** <Alpha, Beta or Production>",
  "",
  "## What",
  "",
  "<What changes.>",
  "",
  "## Rollback",
  "",
  "<The steps.>",
  "",
  "## On call [from Production]",
  "",
  "<Who answers.>",
  "",
].join("\n");
const FILLED = TEMPLATE.replace("<the thing>", "the export")
  .replace("<Alpha, Beta or Production>", "Beta")
  .replace("<What changes.>", "The export gets a progress bar.")
  .replace("<The steps.>", "Revert the commit.");

test("doc: a filled document passes, and its skeleton fails for its placeholders and nothing else", () => {
  assert.deepEqual(checkDoc(TEMPLATE, FILLED, "plan.md"), []);
  const skeleton = checkDoc(TEMPLATE, TEMPLATE, "t.md");
  assert.equal(skeleton.length, 4, skeleton.join("\n"));
  assert.ok(skeleton.every((p) => /is still a placeholder\. Replace it with the real thing\.$/.test(p)), skeleton.join("\n"));
  // A document may add sections of its own between the template's.
  assert.deepEqual(checkDoc(TEMPLATE, FILLED.replace("## Rollback", "## Notes\n\nNone.\n\n## Rollback"), "plan.md"), []);
});

test("doc: a missing, moved or empty section, or a placeholder left, fails with what to do", () => {
  const missing = checkDoc(TEMPLATE, FILLED.replace("## Rollback\n\nRevert the commit.\n", ""), "plan.md");
  assert.deepEqual(missing, ['plan.md: the section "## Rollback" is missing or out of order. Add it after "## What", as the template has it.']);
  const moved = FILLED.replace("## What\n\nThe export gets a progress bar.\n\n## Rollback\n\nRevert the commit.", "## Rollback\n\nRevert the commit.\n\n## What\n\nThe export gets a progress bar.");
  assert.match(checkDoc(TEMPLATE, moved, "plan.md").join("\n"), /"## Rollback" is missing or out of order/);
  const empty = checkDoc(TEMPLATE, FILLED.replace("Revert the commit.", "<!-- later -->"), "plan.md");
  assert.deepEqual(empty, ['plan.md:12: "## Rollback" says nothing. Fill it in, or write why it doesn\'t apply.']);
  const left = checkDoc(TEMPLATE, FILLED.replace("Revert the commit.", "Revert <which commit>."), "plan.md");
  assert.deepEqual(left, ['plan.md:14: "<which commit>" is still a placeholder. Replace it with the real thing.']);
  // Placeholders in code, comments and links aren't placeholders.
  const quiet = FILLED.replace("Revert the commit.", "Run `revert <sha>`, see <https://example.com/x>. <!-- <note> -->");
  assert.deepEqual(checkDoc(TEMPLATE, quiet, "plan.md"), []);
});

test("doc: a section marked [from STAGE] waits for that stage, and must be filled once it's reached", () => {
  assert.deepEqual(checkDoc(TEMPLATE, FILLED, "plan.md"), []);
  const production = checkDoc(TEMPLATE, FILLED.replace("**Stage:** Beta", "**Stage:** Production"), "plan.md");
  assert.deepEqual(production, ['plan.md:18: "<Who answers.>" is still a placeholder. Replace it with the real thing.']);
  const unknown = checkDoc(TEMPLATE, FILLED.replace("**Stage:** Beta", "**Stage:** Live"), "plan.md");
  assert.deepEqual(unknown, ['plan.md:6: its stage, "Live", isn\'t one of the template\'s stages (Alpha, Beta, Production). Use one of them.']);
  const none = checkDoc(TEMPLATE, FILLED.replace("**Stage:** Beta\n", ""), "plan.md");
  assert.match(none.join("\n"), /has no "\*\*Stage:\*\*" line, so no section can wait for a later stage/);
});

test("doc: the command exits 0 on a filled document, 1 with problems and 2 on a file it can't read", () => {
  const root = folder({ "t.md": TEMPLATE, "plan.md": FILLED });
  const ok = kit("doc", join(root, "t.md"), join(root, "plan.md"));
  assert.equal(ok.status, 0, ok.output);
  assert.match(ok.output, /No problems found\./);
  const bad = kit("doc", join(root, "t.md"), join(root, "t.md"));
  assert.equal(bad.status, 1, bad.output);
  assert.match(bad.output, /4 problem\(s\):/);
  assert.equal(kit("doc", join(root, "t.md"), join(root, "gone.md")).status, 2);
  assert.equal(kit("docs").status, 2);
});

// --- decisions ---------------------------------------------------------------------------------

const gap = (id, fields = {}) => ({
  id,
  question: `Question ${id}?`,
  found_by: ["spec review: reviewer-a"],
  decides: "owner",
  decision: "Yes.",
  by: "Dana Whitfield",
  on: "2026-09-30",
  ...fields,
});
const record = (...gaps) => ({ about: "a", brief: "brief.md", gaps });

test("decisions: a decided record passes, and an open gap is fine until --decided asks for none", () => {
  const open = gap("G2", { decides: null, decision: null, by: null, on: null });
  const { problems, summary } = checkDecisions(record(gap("G1"), open), "gaps.json");
  assert.deepEqual(problems, []);
  assert.equal(summary[0], "2 gap(s): 1 decided, 1 open. Who decides: template 0, build 0, owner 1, not assigned 1.");
  assert.equal(summary[1], "  open  G2  not assigned: Question G2?");
  const gate = checkDecisions(record(gap("G1"), open), "gaps.json", { decided: true });
  assert.deepEqual(gate.problems, [
    "gaps.json: 1 gap(s) still open (G2). Each needs a decision, who made it and when, before the spec is agreed.",
  ]);
});

test("decisions: each planted break is named, with what to do", () => {
  const cases = [
    [[gap("G1"), gap("G1")], /gap G1: another gap has the same id/],
    [[gap("Q1")], /gap Q1: its id must be G and a number/],
    [[gap("G1", { decides: "boss" })], /decides is "boss"; use template, build or owner/],
    [[gap("G1", { by: null })], /is decided, so it needs who decided it \(by\)/],
    [[gap("G1", { on: "30 September" })], /is decided, so it needs the day it was decided \(on\), as YYYY-MM-DD/],
    [[gap("G1", { decision: null })], /has who decided and when, but no decision/],
    [[gap("G1", { decides: null })], /is decided, so it needs who decides it: template, build or owner/],
    [[gap("G1", { found_by: [] })], /found_by must list who or what found it/],
    [[gap("G1", { question: " " })], /needs the question the brief leaves open/],
    [[gap("G1", { deciede: "owner" })], /unknown field\(s\) deciede/],
    [[gap("G1", { decision: "<what was decided>" })], /"<what was decided>" is still a placeholder/],
  ];
  for (const [gaps, message] of cases) {
    const { problems } = checkDecisions(record(...gaps), "gaps.json");
    assert.match(problems.join("\n"), message, JSON.stringify(gaps));
  }
  assert.match(checkDecisions({ gaps: [], extra: 1 }, "gaps.json").problems[0], /unknown field\(s\) extra/);
});

test("decisions: the command reads a file, and --decided fails while a gap is open", () => {
  const open = gap("G2", { decides: "build", decision: null, by: null, on: null });
  const root = folder({ "gaps.json": JSON.stringify(record(gap("G1"), open)), "broken.json": "{" });
  const file = join(root, "gaps.json");
  assert.equal(kit("decisions", file).status, 0);
  const gated = kit("decisions", file, "--decided");
  assert.equal(gated.status, 1, gated.output);
  assert.match(gated.output, /open {2}G2 {2}build: Question G2\?/);
  assert.match(kit("decisions", join(root, "broken.json")).output, /isn't valid JSON/);
});

// --- skill -------------------------------------------------------------------------------------

const SKILL = [
  "---",
  "name: tidy-imports",
  "description: Sorts and trims imports in the Python code. Use when asked to tidy or fix imports.",
  "---",
  "",
  "# Tidy imports",
  "",
  "## When it applies",
  "",
  "When imports are out of order or unused. Not for renaming modules.",
  "",
  "## Steps",
  "",
  "1. Run ruff check --fix.",
  "2. Run the tests.",
  "",
  "## References",
  "",
  "- [The rules](rules.md)",
  "",
].join("\n");
const skill = (text = SKILL, name = "tidy-imports", extra = { "rules.md": "# Rules\n" }) =>
  folder(Object.fromEntries([[`${name}/SKILL.md`, text], ...Object.entries(extra).map(([p, c]) => [`${name}/${p}`, c])])) + `/${name}`;

test("skill: a skill folder that follows the rules loads", () => {
  assert.deepEqual(checkSkill(skill()), []);
  const run = kit("skill", skill());
  assert.equal(run.status, 0, run.output);
});

test("skill: each planted break is named, with what to do", () => {
  const cases = [
    [skill(SKILL.replace("name: tidy-imports", "name: Tidy-Imports"), "Tidy-Imports"), /name "Tidy-Imports" must be 1 to 64 lowercase letters, digits and single hyphens/],
    [skill(SKILL.replace("name: tidy-imports", "name: tidy--imports"), "tidy--imports"), /must be 1 to 64 lowercase letters, digits and single hyphens/],
    [skill(SKILL, "tidy"), /name "tidy-imports" must be the folder's name, "tidy"/],
    [skill(SKILL.replace(/^description: .*$/m, `description: ${"x".repeat(1025)}`)), /description must be 1 to 1,024 characters/],
    [skill(SKILL.replace(/^description: .*$/m, `description: ${"x".repeat(1000)}\nwhen_to_use: ${"y".repeat(600)}`)), /run past 1,536 characters together/],
    [skill(SKILL.replace("## Steps", "## How")), /needs a "## Steps" section/],
    [skill(SKILL.replace("1. Run ruff check --fix.\n2. Run the tests.", "Run ruff, then the tests.")), /"## Steps" needs a numbered list/],
    [skill(SKILL, "tidy-imports", {}), /rules\.md isn't in the skill's folder/],
    [skill(SKILL.replace("(rules.md)", "(../outside.md)")), /\.\.\/outside\.md must be a file in the skill's folder, one level deep at most/],
    [skill(SKILL.replace("- [The rules](rules.md)", "Nothing.")), /"## References" links to no file/],
    [skill(SKILL.replace("Run the tests.", "Run <the tests>.")), /"<the tests>" is still a placeholder/],
    [skill(`${SKILL}${"line\n".repeat(500)}`), /Keep it under 500/],
    [skill(SKILL.slice(4)), /must start with "---"/],
  ];
  for (const [path, message] of cases) assert.match(checkSkill(path).join("\n"), message, path);
  assert.match(checkSkill(folder({ "empty/.keep": "" }) + "/empty").join("\n"), /has no SKILL\.md/);
});

// --- changelog ---------------------------------------------------------------------------------

const LOG = "# Changelog\n\n## 2026-09-30, a new check\n\n- Added it.\n\n## 2026-09-29\n\n- Started.\n";

test("changelog: dated entries newest first, each with a bullet, pass; the lab's own changelog passes", () => {
  assert.deepEqual(checkChangelog(LOG).problems, []);
  assert.equal(checkChangelog(LOG).entries, 2);
  const lab = kit("changelog", join(ROOT, "CHANGELOG.md"));
  assert.equal(lab.status, 0, lab.output);
});

test("changelog: an entry out of order, one with no date or no bullet, and a missing title fail", () => {
  const swapped = "# Changelog\n\n## 2026-09-29\n\n- Started.\n\n## 2026-09-30, later\n\n- Added.\n";
  assert.deepEqual(checkChangelog(swapped, "C.md").problems, [
    "C.md:7: 2026-09-30 comes after 2026-09-29 (line 3), but entries go newest first. Move it up.",
  ]);
  assert.match(checkChangelog(LOG.replace("## 2026-09-29", "## Yesterday"), "C.md").problems.join("\n"), /"## Yesterday" must start with the day/);
  assert.match(checkChangelog(LOG.replace("- Added it.", "Added it."), "C.md").problems.join("\n"), /C\.md:3: the entry has no bullets/);
  assert.match(checkChangelog(LOG.replace("# Changelog", "# Changes"), "C.md").problems.join("\n"), /must start with "# Changelog"/);
  assert.match(checkChangelog("# Changelog\n", "C.md").problems.join("\n"), /has no entries/);
  assert.equal(readFileSync(join(ROOT, "CHANGELOG.md"), "utf8").startsWith("# Changelog"), true);
});
