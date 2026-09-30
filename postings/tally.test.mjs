// Proves the tally counts the book's sample and refuses data it cannot trust: every signal, the
// day each posting was read, and the fields that say how the sample was extended.
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
  assert.match(run.stdout, /Included: 45\. Excluded: 38\. Pulled: 2026-09-22\./);
  assert.match(run.stdout, /\| enablement \| 24 \| 53% \|/);
  assert.match(run.stdout, /\| agents \| 39 \| 87% \|/);
  assert.match(run.stdout, /\| python \| 33 \| 73% \|/);
});

test("the book's sample prints its read dates, the gateway's basis and the architect titles", () => {
  const run = tally(SAMPLE);
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /Read on: 2026-09-22 to 2026-09-30 \(2026-09-22: 33, 2026-09-30: 12\)\./);
  assert.match(run.stdout, /Exclusion records by screening date: 2026-09-22: 16, 2026-09-30: 22\./);
  assert.match(run.stdout, /\| gateway \| 6 \| 13% \|/);
  assert.match(run.stdout, /Gateway true on: P09 \(note\), P17 \(reread\), P18 \(reread\), P20 \(reread\), P21 \(reread\), P28 \(reread\)\./);
  assert.match(run.stdout, /Titles containing "architect": 15 of 45 \(read 2026-09-22: 3; later: 12\)\./);
  assert.match(run.stdout, /\| retrieval \| 15 \| 100% \| 13 \| 43% \|/);
  assert.match(run.stdout, / {2}- required: 1 \(P36\)\n/);
});

test("the reader's template tallies as it ships", () => {
  const run = tally(TEMPLATE);
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /Included: 1\. Excluded: 1\. Pulled: YYYY-MM-DD\./);
});

test("deleting the template's mcp line gives chapter 1's refusal, word for word", () => {
  const lines = readFileSync(TEMPLATE, "utf8").split(/\r?\n/);
  writeFileSync(join(work, "my-postings.json"), lines.filter((line) => line.trim() !== '"mcp": false,').join("\n"));
  const run = spawnSync(process.execPath, [join(here, "tally.mjs"), "my-postings.json"], { cwd: work, encoding: "utf8" });
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "");
  assert.equal(
    run.stderr,
    'my-postings.json: 1 problem(s). Nothing was counted.\n- P01: "mcp" is missing. Set it to true or false. Codebook: Mentions the Model Context Protocol.\n',
  );
});

test("a missing gateway code stops the run, quoting the codebook", () => {
  const run = tally(brokenCopy("missing-gateway", (d) => delete d.postings.find((p) => p.id === "P05").gateway));
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "", "nothing may be counted when the data has a problem");
  assert.match(run.stderr, /P05: "gateway" is missing\. Set it to true or false\. Codebook: An LLM gateway that centralizes model access/);
});

test("a posting without its read date stops the run, and so does a date not written YYYY-MM-DD", () => {
  const run = tally(
    brokenCopy("read-dates", (d) => {
      delete d.postings.find((p) => p.id === "P05").readOn;
      d.postings.find((p) => p.id === "P40").readOn = "30 September 2026";
    }),
  );
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "", "nothing may be counted when the data has a problem");
  assert.match(run.stderr, /2 problem\(s\)\. Nothing was counted\./);
  assert.match(run.stderr, /P05: "readOn" is missing\. Set it to the day you read the posting in full, as YYYY-MM-DD\./);
  assert.match(run.stderr, /P40: "readOn" is "30 September 2026"\. Set it to the day you read the posting in full, as YYYY-MM-DD\./);
});

test("a gateway basis must be text, reread or note, and may be left out", () => {
  const run = tally(
    brokenCopy("gateway-basis", (d) => {
      d.postings.find((p) => p.id === "P05").gatewayBasis = "memory";
      delete d.postings.find((p) => p.id === "P06").gatewayBasis;
    }),
  );
  assert.equal(run.status, 1);
  assert.match(run.stderr, /1 problem\(s\)\. Nothing was counted\./);
  assert.match(run.stderr, /P05: "gatewayBasis" is "memory"\. Use one of: text, reread, note, or leave it out\./);
});

test("an architect title without publicWorkAsked stops the run, and so does a level the codebook doesn't have", () => {
  const run = tally(
    brokenCopy("public-work", (d) => {
      delete d.postings.find((p) => p.id === "P36").publicWorkAsked;
      d.postings.find((p) => p.id === "P37").publicWorkAsked = "yes";
    }),
  );
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "", "nothing may be counted when the data has a problem");
  assert.match(run.stderr, /2 problem\(s\)\. Nothing was counted\./);
  assert.match(run.stderr, /P36: "publicWorkAsked" is missing, and the title names an architect\. Use one of: required, asked, preferred, none, not re-read\./);
  assert.match(run.stderr, /P37: "publicWorkAsked" is "yes"\. Use one of: required, asked, preferred, none, not re-read\./);
});

test("an exclusion record without its screening date stops the run", () => {
  const run = tally(brokenCopy("screened-on", (d) => delete d.excluded[0].screenedOn));
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "", "nothing may be counted when the data has a problem");
  assert.match(run.stderr, /excluded record 1: "screenedOn" is missing\. Set it to the day you screened the posting out, as YYYY-MM-DD\./);
});

test("a missing field stops the run and the message says how to fix it", () => {
  const run = tally(brokenCopy("missing-mcp", (d) => delete d.postings.find((p) => p.id === "P05").mcp));
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "", "nothing may be counted when the data has a problem");
  assert.match(run.stderr, /P05: "mcp" is missing\. Set it to true or false\. Codebook: Mentions the Model Context Protocol\./);
});

test("a missing or misspelled field that may be null stops the run, not counted as null", () => {
  const run = tally(
    brokenCopy("renamed-keys", (d) => {
      const p = d.postings.find((p) => p.id === "P05");
      p.yearsRequried = p.yearsRequired;
      delete p.yearsRequired;
      delete d.postings.find((p) => p.id === "P06").degreeRequired;
      delete d.postings.find((p) => p.id === "P07").alsoType;
    }),
  );
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "", "nothing may be counted when the data has a problem");
  assert.match(run.stderr, /3 problem\(s\)\. Nothing was counted\./);
  assert.match(run.stderr, /P05: "yearsRequired" is missing\. Set it to a number, or null if the posting does not say\./);
  assert.match(run.stderr, /P06: "degreeRequired" is missing\. Set it to true, false, or null if the posting does not say\./);
  assert.match(run.stderr, /P07: "alsoType" is missing\. Set it to null, or a type other than the primary one\./);
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
