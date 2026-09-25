// Proves the skills map counts the sample as chapter 1 does and refuses a map that has fallen behind.
// Run: node --test postings/skills.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, sep } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const SAMPLE = join(here, "sample-2026-09-22.json");
const MAP = join(here, "skills-map.json");
const work = mkdtempSync(join(tmpdir(), "skills-"));
after(() => rmSync(work, { recursive: true, force: true }));

const skills = (...args) => spawnSync(process.execPath, [join(here, "skills.mjs"), ...args], { encoding: "utf8" });

// Writes a copy of the map or the sample with one change, so each test breaks exactly one thing.
function brokenCopy(from, name, change) {
  const data = JSON.parse(readFileSync(from, "utf8"));
  change(data);
  const file = join(work, `${name}.json`);
  writeFileSync(file, JSON.stringify(data));
  return file;
}
const chapter = (map, n) => map.chapters.find((ch) => ch.chapter === n);
const withMap = (name, change) => skills(SAMPLE, "--type", "enablement", "--map", brokenCopy(MAP, name, change));

function refused(run, message) {
  assert.equal(run.status, 1, run.stderr);
  assert.equal(run.stdout, "", "nothing may be printed when the map has a problem");
  assert.match(run.stderr, message);
}

test("enablement counts as chapter 1 says: guardrails in 22 of 24, observability and retrieval in 19, evaluation in 18", () => {
  const run = skills(SAMPLE, "--type", "enablement");
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /24 of 45 postings have enablement as their primary kind\. 2 more have it as a second kind/);
  assert.match(run.stdout, /\| guardrails \| 22 of 24 \| 13, 15, 16, 17, 18, 19, 28, 29 \|/);
  assert.match(run.stdout, /\| retrieval \| 19 of 24 \| 9 \|/);
  assert.match(run.stdout, /\| aiObservability \| 19 of 24 \| 26, 27 \|/);
  assert.match(run.stdout, /\| evaluation \| 18 of 24 \| 21, 22, 23 \|/);
  assert.match(run.stdout, /\| servingOrTraining \| 8 of 24 \| not in this book/);
  assert.match(run.stdout, /\| python \| 18 of 24 \| 5, 15, 16, 17 \|/);
});

test("the gateway signal is built by chapters 18 and 27", () => {
  const run = skills(SAMPLE, "--type", "enablement");
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /\| gateway \| 5 of 24 \| 18, 27 \|/);
});

test("the codebook's fields that record how a posting was coded aren't skills, in the sample or a reader's file", () => {
  const run = skills(SAMPLE, "--type", "enablement");
  assert.equal(run.status, 0, run.stderr);
  for (const field of ["readOn", "screenedOn", "gatewayBasis", "publicWorkAsked"]) assert.ok(!run.stdout.includes(field), field);
  const own = skills(TEMPLATE, "--type", "enablement");
  assert.equal(own.status, 0, own.stderr);
  assert.match(own.stdout, /1 of 1 postings have enablement as their primary kind\./);
});

test("--also counts the second kind: coding agents are 11 of 45, as chapter 1 says", () => {
  const run = skills(SAMPLE, "--type", "coding-agents", "--also");
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /11 of 45 postings have coding-agents as their primary or second kind\./);
  assert.match(run.stdout, /\| codingAgents \| 11 of 11 \|/);
});

test("the path starts with Part I and follows chapter 1's table for the kind", () => {
  const run = skills(SAMPLE, "--type", "product-agents");
  assert.equal(run.status, 0, run.stderr);
  assert.match(
    run.stdout,
    /1\. Every path starts with Part I, Getting Started: chapters 1 to 5\.\n2\. Then chapter 1's table: Parts III and V, then chapter 19\.\n {3}- Part III, Tools: chapters 11 to 14\n {3}- Part V, Evaluation: chapters 21 to 23\n {3}- Chapter 19, Permissions, Sandboxes and Human Approval\n/,
  );
});

test("the other chapters go under the most-asked signal they build", () => {
  const run = skills(SAMPLE, "--type", "product-agents");
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, / {3}- 4 of 5: retrieval 9; aiObservability 26, 27\n {3}- 3 of 5: security 20\n/);
  assert.match(run.stdout, /4\. Then the rest, in book order: 30, 32, 33\./);
});

test("--evidence names the checks and what the lab alone can't show", () => {
  const run = skills(SAMPLE, "--type", "enablement", "--evidence");
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /- 23 Evaluations as a Gate\n {2}lab: python\/src\/helpdesk\/gate\.py, python\/evals\/promoted\.json, python\/src\/helpdesk\/model\/budget\.py\n {2}checks: Promotion gate \(python -m helpdesk\.gate check\)\n {2}not shown by the lab: a promotion on a real model/);
});

test("a skill no chapter builds stops the run", () => {
  refused(
    withMap("unbuilt", (m) => (chapter(m, 9).builds = [])),
    /"retrieval" is built by no chapter\. Add it to the chapters that build it, or say why in notCovered\./,
  );
});

test("the map is named from the repository's root, so the message reads the same on every machine", () => {
  const map = brokenCopy(MAP, "named", (m) => (chapter(m, 9).builds = []));
  const run = skills(SAMPLE, "--type", "enablement", "--map", map);
  const shown = relative(join(here, ".."), map).split(sep).join("/");
  assert.equal(run.status, 1);
  assert.ok(run.stderr.startsWith(`${shown}: 1 problem(s). Nothing was printed.`), run.stderr);
  assert.ok(!run.stderr.includes(join(here, "..")), "the root's own path isn't printed");
});

test("a signal added to the codebook must be placed in the map first", () => {
  const sample = brokenCopy(SAMPLE, "new-signal", (d) => {
    d.codebook.fineTuning = "Fine-tunes models.";
    for (const p of d.postings) p.fineTuning = false;
  });
  refused(skills(sample, "--type", "enablement"), /"fineTuning" is built by no chapter\./);
});

test("a skill both built and excused is refused", () => {
  refused(
    withMap("both", (m) => (m.notCovered.retrieval = "not in this book")),
    /"retrieval" is built by a chapter and also listed in notCovered\. Keep one\./,
  );
});

test("a lab path that isn't in the repository stops the run", () => {
  refused(
    withMap("gone", (m) => chapter(m, 9).lab.push("python/src/helpdesk/services/gone.py")),
    /chapter 9: python\/src\/helpdesk\/services\/gone\.py isn't in the repository\. Fix the path, or restore the file\./,
  );
});

test("a check node check.mjs doesn't run stops the run", () => {
  refused(
    withMap("no-check", (m) => (chapter(m, 9).checks = ["Retrieval (python -m helpdesk.kb eval)"])),
    /chapter 9: "Retrieval \(python -m helpdesk\.kb eval\)" isn't a check node check\.mjs runs\./,
  );
});

test("every chapter sits in exactly one part", () => {
  refused(withMap("two-parts", (m) => m.parts[1].chapters.push(11)), /chapter 11 is in 2 parts\. Put it in exactly one\./);
});

test("the table's steps must name parts or chapters the map has", () => {
  refused(withMap("bad-step", (m) => (m.start.applied.steps = ["III", "IX"])), /start\.applied: "IX" is neither a part nor a chapter in the map\./);
});

test("a posting whose codes aren't true or false stops the run", () => {
  const sample = brokenCopy(SAMPLE, "string-flag", (d) => (d.postings.find((p) => p.id === "P05").mcp = "yes"));
  refused(skills(sample, "--type", "enablement"), /P05: "mcp" isn't true or false\./);
});

test("an unknown kind is a usage error that lists the kinds", () => {
  const run = skills(SAMPLE, "--type", "platform");
  assert.equal(run.status, 2);
  assert.match(run.stderr, /KIND is one of: enablement, coding-agents, product-agents, applied, infrastructure\./);
});
