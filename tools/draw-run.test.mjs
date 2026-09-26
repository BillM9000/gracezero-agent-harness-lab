// Proves the drawing of a call record shows every call and how it ended, refusals and cut-off
// answers as failures, groups turns into conversations the way its page says, refuses a line that
// isn't a call rather than drawing part of a record, and makes a page that asks nothing of the
// network and can't be made to run what a record holds.
// Run: node --test tools/draw-run.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";

import { ANSWERED, FIELDS, OUTCOMES, group, parseRecord, render, totals } from "./draw-run.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPT = join(HERE, "draw-run.mjs");
const base = mkdtempSync(join(tmpdir(), "draw-run-"));
after(() => rmSync(base, { recursive: true, force: true }));

// One line of a record, as the budget writes it; override what a test needs.
let clock = 0;
const call = (over = {}) => ({
  at: `2026-09-26T10:00:${String(clock++ % 60).padStart(2, "0")}+00:00`,
  run: "20260926T100000-1",
  command: "gate run",
  part: "tasks",
  model: "claude-opus-5-5",
  outcome: "ok",
  stop_reason: "end_turn",
  error: null,
  input_tokens: 2000,
  output_tokens: 40,
  tokens_from: "estimate",
  usd: 0.01,
  ms: 0,
  prompt: "c94263c782241425",
  team: "",
  route: "",
  deployment: "",
  request_id: null,
  ...over,
});
const lines = (...calls) => calls.map((c) => JSON.stringify(c)).join("\n") + "\n";
const turnsOf = (sections) => sections.flatMap((s) => s.conversations.map((c) => c.turns.map((t) => t.length)));

test("the fields and outcomes are the ones python/src/helpdesk/model/calls.py writes", () => {
  const source = readFileSync(join(HERE, "..", "python", "src", "helpdesk", "model", "calls.py"), "utf8");
  const dataclass = source.slice(source.indexOf("class Call:"), source.indexOf("class CallLog"));
  const fields = [...dataclass.matchAll(/^ {4}(\w+): /gm)].map((m) => m[1]);
  assert.deepEqual(FIELDS, fields, "a call record's fields changed in calls.py: change FIELDS in tools/draw-run.mjs to match");
  const outcomes = source.match(/^OUTCOMES = \(([^)]*)\)/m)[1];
  assert.deepEqual(OUTCOMES, [...outcomes.matchAll(/"([^"]+)"/g)].map((m) => m[1]));
  const answered = source.match(/^ANSWERED = \(([^)]*)\)/m)[1];
  assert.deepEqual(ANSWERED, [...answered.matchAll(/"([^"]+)"/g)].map((m) => m[1]));
});

test("a line that isn't a call is refused with its number, never skipped", () => {
  const good = JSON.stringify(call());
  const { prompt, ...missing } = call();
  const refused = [
    [`${good}\nnot json\n`, /calls\.jsonl:2: not JSON/],
    [`${good}\n${JSON.stringify(missing)}\n`, /calls\.jsonl:2: not a call record; a line has exactly at, run,/],
    [`${JSON.stringify({ ...call(), extra: 1 })}\n`, /calls\.jsonl:1: not a call record/],
    [`${good}\n\n${JSON.stringify(call({ outcome: "fine" }))}\n`, /calls\.jsonl:3: unknown outcome "fine"/],
    [`${JSON.stringify(call({ usd: "0.01" }))}\n`, /calls\.jsonl:1: usd is "0\.01", not a number/],
    [`[1, 2]\n`, /calls\.jsonl:1: not a call record/],
  ];
  for (const [text, message] of refused) assert.throws(() => parseRecord(text, "calls.jsonl"), message);
  assert.equal(parseRecord(`${good}\r\n\r\n${good}\r\n`, "calls.jsonl").length, 2);
});

test("turns that asked for tools stay in one conversation, and any other ending closes it", () => {
  const record = [
    call({ stop_reason: "tool_use", input_tokens: 2000 }),
    call({ stop_reason: "tool_use", input_tokens: 2300 }),
    call({ input_tokens: 2600 }),
    call({ input_tokens: 2600 }), // the same size as the turn before, but that turn ended the conversation
    call({ stop_reason: "tool_use", input_tokens: 2000 }),
    call({ outcome: "refusal", stop_reason: "refusal", input_tokens: 2300 }),
    call({ outcome: "cut off", stop_reason: "max_tokens", input_tokens: 2000 }),
  ];
  const sections = group(record);
  assert.equal(sections.length, 1);
  assert.deepEqual(turnsOf(sections), [[1, 1, 1], [1], [1, 1], [1]]);
  assert.equal(totals(record).toolRounds, 3);
});

test("a smaller request or another prompt starts a new conversation, even after a turn that asked for tools", () => {
  // A conversation that hit the turn limit stops after a tool_use turn; the next one starts small.
  const record = [
    call({ stop_reason: "tool_use", input_tokens: 2000 }),
    call({ stop_reason: "tool_use", input_tokens: 2400 }),
    call({ stop_reason: "tool_use", input_tokens: 2100 }),
    call({ stop_reason: "tool_use", input_tokens: 2500, prompt: "0123456789abcdef" }),
    call({ input_tokens: 2700, prompt: "0123456789abcdef" }),
  ];
  assert.deepEqual(turnsOf(group(record)), [[1, 1], [1], [1, 1]]);
});

test("parts and runs are drawn apart, in the order they first appear", () => {
  const record = [call({ part: "tasks" }), call({ part: "judge" }), call({ part: "tasks", run: "second" })];
  assert.deepEqual(
    group(record).map((s) => `${s.run}/${s.part}`),
    ["20260926T100000-1/tasks", "20260926T100000-1/judge", "second/tasks"],
  );
});

test("an attempt the gateway tries again is the same turn; a refusal outside the gateway ends the conversation", () => {
  const gw = { part: "", command: "gateway", team: "support", route: "summarize", tokens_from: "provider" };
  const record = [
    call({ ...gw, outcome: "unavailable", stop_reason: null, error: "overloaded", input_tokens: 0, output_tokens: 0, usd: 0 }),
    call({ ...gw, deployment: "second-region" }),
    call({ ...gw, outcome: "refusal", stop_reason: "refusal", model: "claude-sonnet-5" }),
    call({ ...gw }),
    call({ ...gw, team: "billing", outcome: "rate limited", stop_reason: null, error: "RateLimited", input_tokens: 0, output_tokens: 0, usd: 0 }),
    call({ ...gw, team: "billing" }),
  ];
  assert.deepEqual(turnsOf(group(record)), [[2], [2], [1], [1]]);
  const plain = [call({ outcome: "refusal", stop_reason: "refusal" }), call()];
  assert.deepEqual(turnsOf(group(plain)), [[1], [1]]);
});

test("refusals, cut-off answers and every other failure count as failed, and the totals add up", () => {
  const record = [
    call({ usd: 0.25, input_tokens: 1000.4, output_tokens: 10 }),
    call({ outcome: "refusal", stop_reason: "refusal", usd: 0.5, input_tokens: 2000, output_tokens: 20 }),
    call({ outcome: "cut off", stop_reason: "max_tokens", usd: 0.25, input_tokens: 3000, output_tokens: 30 }),
    call({ outcome: "error", stop_reason: null, error: "APITimeoutError", usd: 0, input_tokens: 0, output_tokens: 0 }),
    call({ outcome: "over the cap", stop_reason: null, usd: 0, input_tokens: 0, output_tokens: 0 }),
    call({ outcome: "cached", stop_reason: null, usd: 0, input_tokens: 0, output_tokens: 0 }),
  ];
  const t = totals(record);
  assert.equal(t.failedCount, 4);
  assert.deepEqual(t.failed, { refusal: 1, "cut off": 1, "error (APITimeoutError)": 1, "over the cap": 1 });
  const page = render(record, ["calls.jsonl"]);
  assert.match(page, /<b>6<\/b><span>model calls<\/span>/);
  assert.match(page, /<b>6,000<\/b><span>input tokens<\/span>/);
  assert.match(page, /<b>\$1\.00<\/b><span>cost<\/span>/);
  assert.match(page, /<b>4<\/b><span>failed calls<\/span>/);
  assert.match(page, /Failed: 1 cut off, 1 error \(APITimeoutError\), 1 over the cap, 1 refusal\./);
  assert.match(page, /<span class="badge warn">refusal<\/span>/);
  assert.match(page, /<span class="badge warn">cut off, max_tokens<\/span>/);
  assert.match(page, /<span class="badge bad">error \(APITimeoutError\)<\/span>/);
  assert.match(page, /Conversations with a failed call/);
  const clean = render([call(), call()], ["calls.jsonl"]);
  assert.match(clean, /Failed: none/);
  assert.doesNotMatch(clean, /Conversations with a failed call/);
});

test("the page asks nothing of the network, and what a record holds is shown as text, never run", () => {
  const hostile = '<img src="https://example.com/x.png" onerror="alert(1)">';
  const page = render([call({ part: hostile, model: "<script>alert(1)</script>", error: hostile, outcome: "error", stop_reason: null })], [
    join("secret", "folder", "calls.jsonl"),
  ]);
  // Every tag the page has, and its style sheet: the record's text shows up escaped, between them.
  const tags = page.match(/<[^>]*>/g);
  const style = page.slice(page.indexOf("<style>"), page.indexOf("</style>"));
  for (const tag of tags) {
    assert.doesNotMatch(tag, /^<(img|script|link|iframe|object|embed)\b/i, `the page has the tag ${tag}`);
    assert.doesNotMatch(tag, /\s(src|on\w+)=|https?:/i, `the page has the tag ${tag}`);
  }
  assert.doesNotMatch(style, /@import|url\(|https?:/);
  assert.match(page, /&lt;img src=&quot;https:\/\/example\.com\/x\.png&quot; onerror=&quot;alert\(1\)&quot;&gt;/);
  assert.match(page, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(page, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
  assert.match(page, /#0C2340/);
  assert.match(page, /#157A52/);
  // A record's folder can be private: the page names the file alone.
  assert.match(page, /Drawn from calls\.jsonl:/);
  assert.ok(!page.includes("folder"), "the page names the record's folder");
});

test("an empty record draws a page that says so, rather than an empty timeline", () => {
  const page = render([], ["calls.jsonl"]);
  assert.match(page, /No calls recorded/);
  assert.match(page, /--record/);
});

test("from the command line it writes the page beside the record, and refuses a record it can't read", () => {
  const record = join(base, "calls.jsonl");
  writeFileSync(record, lines(call({ stop_reason: "tool_use" }), call({ input_tokens: 2400 }), call({ outcome: "refusal", stop_reason: "refusal" })));
  const run = spawnSync(process.execPath, [SCRIPT, record], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /: 3 calls in 2 conversations, \$0\.0300, 1 failed\./);
  assert.ok(existsSync(join(base, "calls.html")));

  const out = join(base, "drawn", "page.html");
  const second = join(base, "more.jsonl");
  writeFileSync(second, lines(call({ run: "another" })));
  const both = spawnSync(process.execPath, [SCRIPT, record, second, "--out", out], { encoding: "utf8" });
  assert.equal(both.status, 0, both.stderr);
  assert.match(readFileSync(out, "utf8"), /Drawn from calls\.jsonl, more\.jsonl: 2 runs of gate run/);

  const broken = join(base, "broken.jsonl");
  writeFileSync(broken, `${lines(call())}{"at": 1}\n`);
  const bad = spawnSync(process.execPath, [SCRIPT, broken], { encoding: "utf8" });
  assert.equal(bad.status, 1);
  assert.match(bad.stderr, /broken\.jsonl:2: not a call record/);
  assert.ok(!existsSync(join(base, "broken.html")), "a page was drawn from part of a record");

  const missing = spawnSync(process.execPath, [SCRIPT, join(base, "nothing.jsonl")], { encoding: "utf8" });
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /no such file\. python -m helpdesk\.gate run --record FILE writes one\./);
  const none = spawnSync(process.execPath, [SCRIPT], { encoding: "utf8" });
  assert.equal(none.status, 1);
  assert.match(none.stderr, /Usage: node tools\/draw-run\.mjs FILE/);
  const unknown = spawnSync(process.execPath, [SCRIPT, record, "--real"], { encoding: "utf8" });
  assert.equal(unknown.status, 1);
  assert.match(unknown.stderr, /unknown option --real/);
});
