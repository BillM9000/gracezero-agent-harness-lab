// Tests for tools/claims.mjs (Appendix B's proof page): every claim is measured by running its
// command, pass, fail and unknown are told apart, an unknown is never counted as a pass, and a
// claims file that's malformed is refused before anything runs. The commands are small node -e
// scripts, run in a folder of their own.
// Run: node --test tools/claims.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

const CLAIMS = join(dirname(fileURLToPath(import.meta.url)), "claims.mjs");
const base = mkdtempSync(join(tmpdir(), "claims-"));
after(() => rmSync(base, { recursive: true, force: true }));
// Waits, without giving the event loop a turn, for this long.
const pause = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

// Double quotes around node -e's script, which both sh and cmd pass on whole.
const node = (script) => `node -e "${script}"`;
const claim = (id, command, expect = { exit: 0 }, extra = {}) => ({ id, claim: `The ${id} claim holds.`, command, expect, ...extra });

let n = 0;
function measure(claims, ...args) {
  const folder = mkdtempSync(join(base, `case-${++n}-`));
  const file = join(folder, "claims.json");
  writeFileSync(file, JSON.stringify({ about: "a", proof: "proof.md", claims }));
  const run = spawnSync(process.execPath, [CLAIMS, file, "--root", folder, ...args], { encoding: "utf8" });
  const page = join(folder, "proof.md");
  return { status: run.status, output: `${run.stdout}${run.stderr}`, page: existsSync(page) ? readFileSync(page, "utf8") : null };
}

test("claims that hold pass, and the page says each was measured, when, and at what", () => {
  const { status, output, page } = measure([
    claim("exits", node("process.exit(0)")),
    claim("prints", node("console.log('all 3 checks passed')"), { exit: 0, output: "all 3 checks passed" }),
    claim("fails-on-purpose", node("process.exit(4)"), { exit: 4 }),
  ]);
  assert.equal(status, 0, output);
  assert.match(output, /^PASS {5}exits$/m);
  assert.match(output, /3 of 3 claim\(s\) hold\. Wrote .*proof\.md\./);
  assert.match(page, /^# Proof$/m);
  assert.match(page, /^Measured \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC, at no commit \(not a git repository\)\. 3 claim\(s\): 3 pass, 0 fail, 0 unknown\.$/m);
  assert.match(page, /^\| The exits claim holds\. \| pass \| \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC \| `node -e "process\.exit\(0\)"` \|$/m);
  assert.doesNotMatch(page, /What failed/);
});

test("a wrong exit or missing output is a fail, with why and the end of what it printed", () => {
  const { status, output, page } = measure([
    claim("exits", node("console.log('boom'); process.exit(3)")),
    claim("prints", node("console.log('2 checks passed')"), { exit: 0, output: "3 checks passed" }),
  ]);
  assert.equal(status, 1, output);
  assert.match(output, /^FAIL {5}exits: it exited 3, not 0$/m);
  assert.match(output, /^FAIL {5}prints: its output doesn't contain "3 checks passed"$/m);
  assert.match(output, /0 of 2 claim\(s\) hold\./);
  assert.match(page, /2 claim\(s\): 0 pass, 2 fail, 0 unknown\./);
  assert.match(page, /### exits: fail\n\nThe exits claim holds\. Not shown to hold: it exited 3, not 0\.\n\n```\nboom\n```/);
});

test("nothing measured is unknown, not a pass: no command, a missing program, or out of time", () => {
  const started = Date.now();
  const { status, output, page } = measure([
    claim("unmeasured", null),
    claim("missing", "no-such-program-for-claims-test --version"),
    claim("slow", node("setTimeout(() => {}, 2000)"), { exit: 0 }, { timeout_seconds: 1 }),
    claim("holds", node("process.exit(0)")),
  ]);
  // The time limit stops the shell, and on Windows the node it started runs out its 2 seconds, in a
  // folder Windows won't remove while a program is in it; wait for it before the folder goes.
  pause(Math.max(0, 3000 - (Date.now() - started)));
  assert.equal(status, 1, output);
  assert.match(output, /^UNKNOWN {2}unmeasured: no command measures it yet$/m);
  assert.match(output, /^UNKNOWN {2}missing: its program wasn't found \(exit (1|127|9009)\)$/m);
  assert.match(output, /^UNKNOWN {2}slow: it didn't finish within 1 seconds$/m);
  assert.match(output, /1 of 4 claim\(s\) hold\./);
  assert.match(page, /4 claim\(s\): 1 pass, 0 fail, 3 unknown\./);
  assert.match(page, /^\| The unmeasured claim holds\. \| unknown \| .* \| none \|$/m);
});

test("a malformed claims file, or one with a placeholder left, is refused and no page is written", () => {
  const cases = [
    [[claim("a", node("1")), claim("a", node("1"))], /a: another claim has the same id/],
    [[claim("Bad Id", node("1"))], /its id must be lowercase words joined by hyphens/],
    [[claim("a", node("1"), { exit: "0" })], /expect must be \{ "exit": CODE \}/],
    [[claim("a", node("1"), { exit: 0, output: "" })], /expect\.output must be the text/],
    [[claim("a", "")], /command must be the command that measures it, or null/],
    [[claim("a", node("1"), { exit: 0 }, { timeout_seconds: 0 })], /timeout_seconds must be a whole number of seconds/],
    [[claim("a", node("1"), { exit: 0 }, { owner: "Sam" })], /unknown field\(s\) owner/],
    [[claim("a", "<the command that measures it>")], /"<the command that measures it>" is still a placeholder/],
  ];
  for (const [claims, message] of cases) {
    const { status, output, page } = measure(claims);
    assert.equal(status, 1, output);
    assert.match(output, message);
    assert.match(output, /so nothing was measured and no page was written/);
    assert.equal(page, null);
  }
});
