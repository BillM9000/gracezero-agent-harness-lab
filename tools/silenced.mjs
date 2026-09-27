// Lines that switch a rule off instead of meeting it (chapter 26): an inline exception to a linter,
// a type checker or a test runner. Chapters 16 and 17 ask what an agent does after a rule stops it:
// fix the code the way the message says, or silence the rule. The fix loop (tools/fix-loop.mjs)
// stops when an attempt adds one of these lines, and tools/measure.mjs counts them in history.
//
// Both kinds count: a line's own exception, and one that switches a rule off for the whole file or
// a stretch of it (`# ruff: noqa: F401` at the top, which `# noqa` alone doesn't match, or
// `pytestmark = pytest.mark.skip`).
//
// It's a list of patterns, so it finds what it names and nothing else: a rule turned off in a
// configuration file is a change to the checks, which the fix loop's protected list
// (tools/protected.mjs) catches. And a line can match for an innocent reason, such as a test that
// writes one on purpose. Read the lines it reports before you believe a count.
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const SILENCED = new RegExp(
  [
    String.raw`#\s*noqa\b`, // ruff and flake8, on one line
    String.raw`#\s*(ruff|flake8)\s*:\s*(noqa|disable)\b`, // ruff and flake8, for the whole file or a stretch
    String.raw`#\s*fmt\s*:\s*(off|skip)\b`, // the formatter
    String.raw`#\s*type:\s*ignore\b`, // Python type checkers
    String.raw`#\s*(mypy|pyright)\s*:\s*(ignore|basic|disable)`, // the same, for a file
    String.raw`#\s*pylint\s*:\s*disable`,
    String.raw`#\s*pragma:\s*no\s*(cover|branch)\b`, // coverage
    String.raw`#\s*nosec\b`, // bandit
    String.raw`#\s*HDK\d+:`, // the lab's own rule's exception (chapter 17), reason and all
    String.raw`\bpytest\.mark\.(skip|skipif|xfail)\b`, // a decorator, or pytestmark for a whole file
    String.raw`\bpytest\.(skip|xfail|importorskip)\(`,
    String.raw`eslint-disable`,
    String.raw`@ts-(ignore|expect-error|nocheck)\b`,
    String.raw`\b(it|test|describe)\.(skip|only|skipIf|runIf)\b`, // .only skips every other test
    String.raw`\{\s*(skip|todo)\s*:`, // node:test's options
  ].join("|"),
);
const MARKDOWN = /\.md$/i;

// The lines a unified diff adds, each with its file, Markdown left out.
export function addedLines(diff) {
  const added = [];
  let file = null;
  for (const line of diff.replaceAll("\r\n", "\n").split("\n")) {
    if (line.startsWith("+++ ")) {
      const name = line.slice(4);
      file = name === "/dev/null" ? null : name.replace(/^b\//, "");
    } else if (line.startsWith("diff --git ")) {
      file = null;
    } else if (file && !MARKDOWN.test(file) && line.startsWith("+")) {
      added.push({ file, text: line.slice(1) });
    }
  }
  return added;
}

export const silenced = (lines) => lines.filter(({ text }) => SILENCED.test(text)).map(({ file, text }) => `${file}: ${text.trim()}`);

// Every silencing line the working tree adds to `base` (a commit; the fix loop passes the one it
// started from, since an agent can move HEAD): changed files, and new files git doesn't ignore.
// --text shows the lines of a file .gitattributes marks as binary.
export function workingSilenced(root, base = "HEAD") {
  const run = (args) => spawnSync("git", args, { cwd: root, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 }).stdout ?? "";
  const lines = addedLines(run(["diff", base, "--unified=0", "--no-color", "--no-ext-diff", "--text"]));
  for (const file of run(["ls-files", "--others", "--exclude-standard", "-z"]).split("\0").filter(Boolean)) {
    if (MARKDOWN.test(file)) continue;
    let text = "";
    try {
      text = readFileSync(join(root, file), "utf8");
    } catch {
      continue;
    }
    for (const line of text.split("\n")) lines.push({ file, text: line });
  }
  return silenced(lines);
}

// What `after` has that `before` didn't, counting repeats: a line added twice is two lines.
export function newlyAdded(before, after) {
  const left = new Map();
  for (const line of before) left.set(line, (left.get(line) ?? 0) + 1);
  return after.filter((line) => {
    const n = left.get(line) ?? 0;
    if (n > 0) {
      left.set(line, n - 1);
      return false;
    }
    return true;
  });
}
