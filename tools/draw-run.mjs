// Draws a record of model calls as one HTML page, so you can see what your agent did (chapter 26).
//
// python -m helpdesk.gate run --record FILE, and the gateway (chapter 27), write one JSON line a call:
// when, which command and part, which model, how it ended, the tokens and what they cost, how long
// it took, and a fingerprint of the prompt. python -m helpdesk.calls FILE sums a record up; this
// draws it: every call in order, grouped into conversations and turns, with how each call ended,
// refusals and cut-off answers marked as failures, and the totals at the top.
//
// The record holds no conversation (chapter 26: an audit trail that copied it would be one more place
// customers' words live), so what the page calls a conversation is inferred, and the page says how:
//   - each line is one turn: one request to the model and how it ended;
//   - a turn that stopped with "tool_use" asked for tools, which ran before the next turn. The record
//     doesn't say which tools or how many, only that there was a round of them;
//   - a conversation goes on after a tool_use turn, and after an attempt the gateway tries again
//     elsewhere ("unavailable", or a refusal on a route with another model), which the next line for
//     the same request repeats as a retry of the same turn; it ends after any other line;
//   - a line with a different prompt fingerprint, team or route, or with fewer input tokens than the
//     turn before it (a conversation's history only grows), starts a new conversation.
//
// The page is self-contained: no scripts, no fonts, no requests to anywhere. It names the record
// files by their base names only, so it can be shared without showing where they lived.
//
// Usage: node tools/draw-run.mjs FILE [FILE ...] [--out PAGE.html]
// Without --out, the page goes beside the first file, with .html in place of its extension.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

// The fields of a line and the ways a call can end, as python/src/helpdesk/model/calls.py defines
// them. tools/draw-run.test.mjs fails when the two disagree.
export const FIELDS = [
  "at",
  "run",
  "command",
  "part",
  "model",
  "outcome",
  "stop_reason",
  "error",
  "input_tokens",
  "output_tokens",
  "tokens_from",
  "usd",
  "ms",
  "prompt",
  "team",
  "route",
  "deployment",
  "request_id",
];
export const OUTCOMES = ["ok", "refusal", "cut off", "error", "over the cap", "unavailable", "rate limited", "over the budget", "cached"];
export const ANSWERED = ["ok", "cached"];
const NUMBERS = ["input_tokens", "output_tokens", "usd", "ms"];

// Every line of one record. A line that isn't a call is refused with its number, never skipped: a
// drawing of part of a record would look like a drawing of all of it.
export function parseRecord(text, name) {
  const calls = [];
  const expected = [...FIELDS].sort().join(",");
  text.split(/\r?\n/).forEach((line, index) => {
    const number = index + 1;
    if (!line.trim()) return;
    let found;
    try {
      found = JSON.parse(line);
    } catch (error) {
      throw new Error(`${name}:${number}: not JSON (${error.message}).`);
    }
    if (!found || typeof found !== "object" || Array.isArray(found) || Object.keys(found).sort().join(",") !== expected) {
      throw new Error(`${name}:${number}: not a call record; a line has exactly ${FIELDS.join(", ")}.`);
    }
    if (!OUTCOMES.includes(found.outcome)) throw new Error(`${name}:${number}: unknown outcome ${JSON.stringify(found.outcome)}.`);
    for (const field of NUMBERS) {
      if (typeof found[field] !== "number" || !Number.isFinite(found[field])) {
        throw new Error(`${name}:${number}: ${field} is ${JSON.stringify(found[field])}, not a number.`);
      }
    }
    calls.push(found);
  });
  return calls;
}

// An attempt the gateway (chapter 27) tries again elsewhere: a deployment that couldn't answer, or a
// model that refused, when the route has another. The next line for the same team, route and prompt
// is the same turn again. (When a refusal was the route's last word, a new request with the same
// prompt right after it would be drawn as a retry: the record can't tell the two apart.)
const retried = (call) => call.outcome === "unavailable" || (call.route !== "" && call.outcome === "refusal");
const sameRequest = (a, b) => a.team === b.team && a.route === b.route && a.prompt === b.prompt;

// The calls grouped as the page draws them: by run and part, in the order they first appear, then
// into conversations, each a list of turns, each turn its attempts (one, unless the gateway retried).
export function group(calls) {
  const sections = new Map();
  for (const call of calls) {
    const key = `${call.run}\u0000${call.part}`;
    if (!sections.has(key)) sections.set(key, { run: call.run, command: call.command, part: call.part, conversations: [], open: null });
    const section = sections.get(key);
    let open = section.open;
    const last = open?.calls.at(-1);
    const retry = Boolean(last && retried(last) && sameRequest(last, call));
    // A conversation's history only grows, so fewer input tokens than the turn before means a new one.
    const shrank = last && last.input_tokens > 0 && call.input_tokens > 0 && call.input_tokens < last.input_tokens;
    if (!open || (!retry && (!sameRequest(last, call) || shrank))) {
      open = { calls: [], turns: [] };
      section.conversations.push(open);
    }
    if (retry && open.turns.length) open.turns.at(-1).push(call);
    else open.turns.push([call]);
    open.calls.push(call);
    section.open = call.stop_reason === "tool_use" || retried(call) ? open : null;
  }
  return [...sections.values()].map(({ open, ...section }) => section);
}

export function totals(calls) {
  const sum = (field) => calls.reduce((total, call) => total + call[field], 0);
  const failed = {};
  for (const call of calls) {
    if (ANSWERED.includes(call.outcome)) continue;
    const kind = call.error ? `${call.outcome} (${call.error})` : call.outcome;
    failed[kind] = (failed[kind] ?? 0) + 1;
  }
  return {
    calls: calls.length,
    toolRounds: calls.filter((call) => call.stop_reason === "tool_use").length,
    inputTokens: sum("input_tokens"),
    outputTokens: sum("output_tokens"),
    usd: sum("usd"),
    ms: sum("ms"),
    failed,
    failedCount: Object.values(failed).reduce((a, b) => a + b, 0),
    estimated: calls.filter((call) => call.tokens_from === "estimate").length,
    reported: calls.filter((call) => call.tokens_from === "provider").length,
  };
}

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);
const whole = (n) => Math.round(n).toLocaleString("en-US");
export const dollars = (n) => `$${n >= 1 ? n.toFixed(2) : n.toFixed(4)}`;
const plural = (n, one, many = `${one}s`) => `${whole(n)} ${n === 1 ? one : many}`;
// How a line ended, in words: the outcome, and the stop reason when it says more.
const ended = (call) => {
  const reason = call.stop_reason && call.stop_reason !== call.outcome ? `, ${call.stop_reason}` : "";
  return `${call.outcome}${call.error ? ` (${call.error})` : ""}${reason}`;
};
// A section's name: its part, or for the gateway's lines, which carry none, the command.
const partName = (section) => section.part || section.command || "(no part)";
const tone = (call) => (ANSWERED.includes(call.outcome) ? "good" : call.outcome === "refusal" || call.outcome === "cut off" ? "warn" : "bad");

const STYLE = `
:root { --navy: #0C2340; --green: #157A52; --ink: #1d2733; --muted: #5a6675; --line: #d9dee5; --paper: #ffffff; --wash: #f4f6f9; --warn: #8a5a00; --warn-bg: #fff4dc; --bad: #a3261b; --bad-bg: #fde8e6; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--wash); color: var(--ink); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
header { background: var(--navy); color: #fff; padding: 20px 16px; }
header h1 { margin: 0 0 4px; font-size: 1.4rem; }
header p { margin: 0; color: #c9d3e0; overflow-wrap: anywhere; }
main { max-width: 960px; margin: 0 auto; padding: 16px; }
section { background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin: 0 0 16px; }
h2 { margin: 0 0 12px; font-size: 1.15rem; color: var(--navy); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
.card { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; }
.card b { display: block; font-size: 1.25rem; color: var(--navy); font-variant-numeric: tabular-nums; }
.card span { color: var(--muted); font-size: 0.85rem; }
.card.bad b { color: var(--bad); }
.card.good b { color: var(--green); }
.table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 4px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { color: var(--muted); font-weight: 600; font-size: 0.85rem; }
p.note, li.note { color: var(--muted); font-size: 0.9rem; }
details.part > summary { font-weight: 600; color: var(--navy); cursor: pointer; }
details.conversation { border-left: 3px solid var(--green); margin: 10px 0; padding: 2px 0 2px 10px; }
details.conversation.failed { border-left-color: var(--bad); }
details.conversation > summary { cursor: pointer; overflow-wrap: anywhere; }
.turn { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; padding: 6px 0; border-bottom: 1px dashed var(--line); }
.turn .label { width: 4.5rem; color: var(--muted); font-size: 0.85rem; }
.turn .bars { flex: 1 1 180px; min-width: 120px; }
.bar { height: 8px; border-radius: 4px; margin: 2px 0; }
.bar.in { background: var(--navy); }
.bar.out { background: var(--green); }
.turn .numbers { flex: 1 1 260px; font-size: 0.85rem; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.badge { display: inline-block; padding: 0 8px; border-radius: 10px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.badge.good { background: #e3f3ec; color: var(--green); }
.badge.warn { background: var(--warn-bg); color: var(--warn); }
.badge.bad { background: var(--bad-bg); color: var(--bad); }
.tools { font-size: 0.85rem; color: var(--green); padding: 2px 0 2px 4.5rem; }
.legend span { display: inline-block; width: 12px; height: 8px; border-radius: 4px; margin-right: 4px; }
ul.failures { margin: 0; padding-left: 20px; }
a { color: var(--navy); }
footer { color: var(--muted); font-size: 0.85rem; text-align: center; padding: 0 16px 24px; }
@media (max-width: 520px) { .turn .label { width: auto; } .tools { padding-left: 0; } }
`;

function turnRows(turns, scale) {
  const rows = [];
  turns.forEach((attempts, index) => {
    for (const [a, call] of attempts.entries()) {
      const label = a === 0 ? `Turn ${index + 1}` : "retry";
      const width = (n) => (scale > 0 && n > 0 ? Math.max(0.5, (n / scale) * 100).toFixed(1) : "0");
      const where = [call.team && `team ${call.team}`, call.route && `route ${call.route}`, call.deployment && `at ${call.deployment}`].filter(Boolean).join(", ");
      rows.push(
        `<div class="turn"><span class="label">${label}</span>` +
          `<span class="bars" aria-hidden="true"><div class="bar in" style="width:${width(call.input_tokens)}%"></div><div class="bar out" style="width:${width(call.output_tokens)}%"></div></span>` +
          `<span class="numbers">${whole(call.input_tokens)} in, ${whole(call.output_tokens)} out, ${dollars(call.usd)}, ${whole(call.ms)} ms, ${escape(call.model)}${where ? `, ${escape(where)}` : ""} ` +
          `<span class="badge ${tone(call)}">${escape(ended(call))}</span></span></div>`,
      );
    }
    if (attempts.at(-1).stop_reason === "tool_use") {
      rows.push(`<div class="tools">asked for tools; they ran${index + 1 < turns.length ? ", and their results went into the next turn" : ", and the record ends before another turn"}</div>`);
    }
  });
  return rows.join("\n");
}

export function render(calls, sources) {
  const t = totals(calls);
  const sections = group(calls);
  const conversations = sections.reduce((n, s) => n + s.conversations.length, 0);
  const turnCount = sections.reduce((n, s) => n + s.conversations.reduce((m, c) => m + c.turns.length, 0), 0);
  const scale = Math.max(0, ...calls.map((c) => Math.max(c.input_tokens, c.output_tokens)));
  const names = sources.map((s) => escape(basename(s))).join(", ");
  const runs = [...new Set(calls.map((c) => c.run))];
  const commands = [...new Set(calls.map((c) => c.command))].map(escape).join(", ");
  const times = calls.map((c) => c.at).filter(Boolean).sort();
  const span = times.length ? `${escape(times[0])} to ${escape(times.at(-1))}` : "";
  const openAll = conversations <= 20;

  const head = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What the agent did</title>
<style>${STYLE}</style>
</head>
<body>
<header><h1>What the agent did</h1><p>Drawn from ${names}${calls.length ? `: ${plural(runs.length, "run")} of ${commands}, ${span}` : ""}.</p></header>
<main>`;
  const foot = `</main>
<footer>Drawn by tools/draw-run.mjs from a record of model calls (chapter 26). The record keeps no conversation, only what each call cost and how it ended.</footer>
</body>
</html>
`;
  if (!calls.length) {
    return `${head}
<section><h2>No calls recorded</h2><p>The record is empty. A record that goes quiet looks just like a quiet day (chapter 26), so check that the command you ran was given <code>--record</code> and made calls.</p></section>
${foot}`;
  }

  const card = (value, label, kind = "") => `<div class="card ${kind}"><b>${value}</b><span>${label}</span></div>`;
  const tokenNote =
    t.estimated && !t.reported
      ? "Every token count here is an estimate from characters: the mock reports none."
      : t.estimated
        ? `Token counts are the provider's for ${plural(t.reported, "call")} and estimates from characters for ${whole(t.estimated)}.`
        : "Token counts are the provider's own.";
  const failedList = Object.entries(t.failed)
    .sort()
    .map(([kind, n]) => `${whole(n)} ${escape(kind)}`)
    .join(", ");

  // By part and model, as python -m helpdesk.calls prints it.
  const byPart = new Map();
  for (const call of calls) {
    const key = `${call.part || "-"}\u0000${call.model}`;
    if (!byPart.has(key)) byPart.set(key, []);
    byPart.get(key).push(call);
  }
  const partRows = [...byPart]
    .map(([key, group]) => {
      const [part, model] = key.split("\u0000");
      const g = totals(group);
      return `<tr><td>${escape(part)}</td><td>${escape(model)}</td><td>${whole(g.calls)}</td><td>${whole(g.inputTokens)}</td><td>${whole(g.outputTokens)}</td><td>${dollars(g.usd)}</td><td>${whole(g.failedCount)}</td></tr>`;
    })
    .join("\n");

  const failures = [];
  let id = 0;
  const parts = sections
    .map((section) => {
      const items = section.conversations
        .map((conversation, index) => {
          const c = totals(conversation.calls);
          const anchor = `c${++id}`;
          const last = conversation.calls.at(-1);
          const title = `Conversation ${index + 1}`;
          if (c.failedCount) {
            const kinds = Object.entries(c.failed)
              .sort()
              .map(([kind, n]) => `${whole(n)} ${kind}`)
              .join(", ");
            failures.push(`<li><a href="#${anchor}">${escape(partName(section))}, ${title}</a>: ${escape(kinds)}; ended ${escape(ended(last))}</li>`);
          }
          const open = openAll || c.failedCount ? " open" : "";
          const turns = conversation.turns.length;
          return (
            `<details class="conversation${c.failedCount ? " failed" : ""}" id="${anchor}"${open}><summary>${title}: ${plural(turns, "turn")}, ${plural(c.toolRounds, "tool round")}, ` +
            `${whole(c.inputTokens)} in, ${whole(c.outputTokens)} out, ${dollars(c.usd)}; ended <span class="badge ${tone(last)}">${escape(ended(last))}</span></summary>\n` +
            `${turnRows(conversation.turns, scale)}\n</details>`
          );
        })
        .join("\n");
      const s = totals(section.conversations.flatMap((c) => c.calls));
      const label = `${escape(partName(section))}: ${plural(section.conversations.length, "conversation")}, ${plural(s.calls, "call")}, ${dollars(s.usd)}${runs.length > 1 ? `, run ${escape(section.run)}` : ""}`;
      return `<details class="part" open><summary>${label}</summary>\n${items}\n</details>`;
    })
    .join("\n");

  return `${head}
<section><h2>Totals</h2>
<div class="cards">
${card(whole(t.calls), "model calls")}
${card(whole(conversations), "conversations")}
${card(whole(turnCount), "turns")}
${card(whole(t.toolRounds), "tool rounds")}
${card(whole(t.inputTokens), "input tokens")}
${card(whole(t.outputTokens), "output tokens")}
${card(dollars(t.usd), "cost")}
${card(whole(t.failedCount), "failed calls", t.failedCount ? "bad" : "good")}
</div>
<p class="note">${tokenNote} Failed: ${t.failedCount ? `${failedList}.` : "none (no refusals, cut-off answers, errors or refused calls)."}</p>
</section>
<section><h2>By part and model</h2><div class="table"><table>
<tr><th>part</th><th>model</th><th>calls</th><th>input tokens</th><th>output tokens</th><th>cost</th><th>failed</th></tr>
${partRows}
</table></div></section>
${failures.length ? `<section><h2>Conversations with a failed call</h2><ul class="failures">\n${failures.join("\n")}\n</ul></section>` : ""}
<section><h2>Timeline</h2>
<p class="note legend"><span style="background:#0C2340"></span>input tokens <span style="background:#157A52"></span>output tokens, each bar against the largest in the record. Each line is one turn, one request to the model. A turn that stopped with tool_use asked for tools, which ran before the next turn; the record doesn't say which tools. An attempt the gateway tried again elsewhere is followed by its retry. A conversation ends after any other ending, and a new prompt, team or route, or fewer input tokens than the turn before, starts a new one. That grouping is inferred: the record keeps no conversation.${openAll ? "" : " Conversations with a failed call are open; click any other to see its turns."}</p>
${parts}
</section>
${foot}`;
}

function option(args, name) {
  const at = args.indexOf(name);
  if (at === -1) return undefined;
  const value = args[at + 1];
  if (!value || value.startsWith("--")) throw new Error(`${name} needs a file.`);
  return value;
}

export function main(args) {
  const out = option(args, "--out");
  const unknown = args.filter((a, i) => a.startsWith("--") && a !== "--out" && args[i - 1] !== "--out");
  if (unknown.length) throw new Error(`unknown option ${unknown[0]}.`);
  const files = args.filter((a, i) => !a.startsWith("--") && args[i - 1] !== "--out");
  if (!files.length) throw new Error("name a record file.");
  const calls = [];
  for (const file of files) {
    if (!existsSync(file)) throw new Error(`${file}: no such file. python -m helpdesk.gate run --record FILE writes one.`);
    calls.push(...parseRecord(readFileSync(file, "utf8"), file));
  }
  const page = out ?? join(dirname(files[0]), `${basename(files[0], extname(files[0]))}.html`);
  mkdirSync(dirname(page), { recursive: true });
  writeFileSync(page, render(calls, files));
  const t = totals(calls);
  const conversations = group(calls).reduce((n, s) => n + s.conversations.length, 0);
  return `Wrote ${page}: ${plural(t.calls, "call")} in ${plural(conversations, "conversation")}, ${dollars(t.usd)}, ${whole(t.failedCount)} failed.`;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    console.log(main(process.argv.slice(2)));
  } catch (error) {
    console.error(`draw-run: ${error.message}\nUsage: node tools/draw-run.mjs FILE [FILE ...] [--out PAGE.html]`);
    process.exit(1);
  }
}
