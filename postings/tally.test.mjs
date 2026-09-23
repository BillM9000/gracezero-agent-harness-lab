// Proves the tally counts the book's sample and refuses data it cannot trust.
// Run: node --test postings/tally.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const SAMPLE = join(here, "sample-2026-09-22.json");
const TEMPLATE = join(here, "my-postings.template.json");
const work = mkdtempSync(join(tmpdir(), "tally-"));
after(() => rmSync(work, { recursive: true, force: true }));

const tally = (file) => spawnSync(process.execPath, [join(here, "tally.mjs"), file], { encoding: "utf8" });

// Writes a copy of the sample with one change, so each test breaks exactly one thing.
function brokenCopy(name, change) {
  const data = JSON.parse(readFileSync(SAMPLE, "utf8"));
  change(data);
  const file = join(work, `${name}.json`);
  writeFileSync(file, JSON.stringify(data));
  return file;
}

test("the book's sample tallies to the counts printed in chapter 1", () => {
  const run = tally(SAMPLE);
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /Included: 33\. Excluded: 16\. Pulled: 2026-09-22\./);
  assert.match(run.stdout, /\| enablement \| 15 \| 45% \|/);
  assert.match(run.stdout, /\| agents \| 28 \| 85% \|/);
  assert.match(run.stdout, /\| python \| 27 \| 82% \|/);
});

test("the reader's template tallies as it ships", () => {
  const run = tally(TEMPLATE);
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /Included: 1\./);
});

test("a missing field stops the run and the message says how to fix it", () => {
  const run = tally(brokenCopy("missing-mcp", (d) => delete d.postings.find((p) => p.id === "P05").mcp));
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "", "nothing may be counted when the data has a problem");
  assert.match(run.stderr, /P05: "mcp" is missing\. Set it to true or false\. Codebook: Mentions the Model Context Protocol\./);
});

test("a value that is not true or false is refused, not counted as no", () => {
  const run = tally(brokenCopy("string-flag", (d) => (d.postings[0].python = "yes")));
  assert.equal(run.status, 1);
  assert.match(run.stderr, /P01: "python" is "yes"\. Set it to true or false\./);
});

test("an unknown job type is refused and the allowed types are listed", () => {
  const run = tally(brokenCopy("bad-type", (d) => (d.postings[1].type = "platform")));
  assert.equal(run.status, 1);
  assert.match(run.stderr, /P02: type is "platform"\. Use one of: infrastructure, enablement, product-agents, coding-agents, applied\./);
});

test("a duplicate id is refused, so one posting cannot count twice", () => {
  const run = tally(brokenCopy("duplicate-id", (d) => (d.postings[2].id = "P01")));
  assert.equal(run.status, 1);
  assert.match(run.stderr, /P01: id is used twice\./);
});

test("every problem is listed at once, not one per run", () => {
  const run = tally(
    brokenCopy("two-problems", (d) => {
      delete d.postings[0].mcp;
      d.postings[1].type = "platform";
    }),
  );
  assert.equal(run.status, 1);
  assert.match(run.stderr, /2 problem\(s\)\. Nothing was counted\./);
});
