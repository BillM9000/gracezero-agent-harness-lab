// Proves every template in templates/ (the book's Appendix B) still works: each passes the check it
// was written for, or runs, and fails when a violation is planted. Without this, a template could
// drift from the lab it was cut from, and a reader would copy something that no longer works.
//
// The one template no code runs is templates/assessment-checklist.md, chapter 31's checklist for a
// person. The AGENTS.md and CLAUDE.md templates end in .template, not .md, so no tool reads them as
// the instructions for the templates folder (an agent reads the nearest AGENTS.md), and so a change
// to them runs the full checks in CI, not only the document checks.
// Run: node --test tools/templates.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { after, test } from "node:test";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const TEMPLATES = join(ROOT, "templates");
const PYTHON_DIR = join(ROOT, "python");
const PYTHON = join(PYTHON_DIR, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
// No .pyc files: a template changed and put back within a second must not run from a stale cache.
const ENV = { ...process.env, PYTHONDONTWRITEBYTECODE: "1" };
const base = mkdtempSync(join(tmpdir(), "templates-"));
after(() => rmSync(base, { recursive: true, force: true }));

const read = (path) => readFileSync(path, "utf8").replaceAll("\r\n", "\n");
function run(program, args, cwd = ROOT) {
  const result = spawnSync(program, args, { cwd, encoding: "utf8", env: ENV });
  return { status: result.status, output: `${result.stdout ?? ""}${result.stderr ?? ""}${result.error?.message ?? ""}` };
}
const node = (...args) => run(process.execPath, args);
const python = (args, cwd = PYTHON_DIR) => run(PYTHON, args, cwd);

let n = 0;
function folder(files) {
  const root = join(base, `case-${++n}`);
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  return root;
}

// --- The AGENTS.md skeleton (chapter 6) ---------------------------------------------------------

const AGENTS = read(join(TEMPLATES, "AGENTS.md.template"));
const CLAUDE = read(join(TEMPLATES, "CLAUDE.md.template"));

test("the AGENTS.md template, beside the CLAUDE.md template that imports it, passes tools/instruction-files.mjs", () => {
  const root = folder({ "AGENTS.md": AGENTS, "CLAUDE.md": CLAUDE });
  const { status, output } = node("tools/instruction-files.mjs", root, "--max-tokens", "4000");
  assert.equal(status, 0, output);
  assert.match(output, /^CLAUDE\.md +session start .* AGENTS\.md$/m);
  assert.match(output, /No problems found\./);
});

test("the CLAUDE.md template is the lab's own CLAUDE.md, word for word", () => {
  assert.equal(CLAUDE, read(join(ROOT, "CLAUDE.md")));
});

test("a CLAUDE.md without the template's import line fails the same check", () => {
  const root = folder({ "AGENTS.md": AGENTS, "CLAUDE.md": CLAUDE.replace("@AGENTS.md\n", "") });
  const { status, output } = node("tools/instruction-files.mjs", root, "--max-tokens", "4000");
  assert.equal(status, 1, output);
  assert.match(output, /CLAUDE\.md sits beside AGENTS\.md but doesn't import it/);
});

// --- The work list (chapter 10) -----------------------------------------------------------------

test("the work list template passes tools/progress.mjs, with its done item's proof found", () => {
  const { status, output } = node("tools/progress.mjs", "templates");
  assert.equal(status, 0, output);
  assert.match(output, /Done 1, in progress 0, to do 1\./);
  assert.match(output, /Next: next-item: /);
  assert.match(output, /Last session \(progress\/log\.md\):/);
});

test("the work list template fails when an item is marked done with no test behind it", () => {
  const root = join(base, `case-${++n}`);
  cpSync(TEMPLATES, root, { recursive: true });
  const list = JSON.parse(read(join(root, "progress", "features.json")));
  list.features[1].status = "done";
  writeFileSync(join(root, "progress", "features.json"), JSON.stringify(list));
  const { status, output } = node("tools/progress.mjs", root);
  assert.equal(status, 1, output);
  assert.match(output, /next-item: is marked done but names no proof/);
});

// --- The CI workflows (chapter 24) --------------------------------------------------------------

const WORKFLOWS = ["ci", "docs", "nightly"];
const lines = (text) => text.split("\n").map((line) => line.trimEnd());
const code = (text) => lines(text).filter((line) => line.trim() !== "" && !line.trim().startsWith("#"));

test("each workflow template is the lab's own workflow, trimmed, in the same order", () => {
  for (const name of WORKFLOWS) {
    const template = read(join(TEMPLATES, "workflows", `${name}.yml`));
    assert.doesNotMatch(template, /\t/, `${name}.yml has a tab; YAML indents with spaces`);
    const real = lines(read(join(ROOT, ".github", "workflows", `${name}.yml`)));
    let at = 0;
    for (const line of code(template)) {
      const found = real.indexOf(line, at);
      assert.ok(found >= 0, `templates/workflows/${name}.yml: "${line.trim()}" isn't in .github/workflows/${name}.yml after line ${at}. Bring the template back in line with the lab's workflow.`);
      at = found + 1;
    }
  }
});

// A token that can write lets a compromised step change the repository, and a tag can be moved to
// other code after it was reviewed; a commit SHA can't.
test("every workflow, the lab's and the templates', gives its token read access alone and pins each action to a commit", () => {
  for (const name of WORKFLOWS) {
    for (const where of [`templates/workflows/${name}.yml`, `.github/workflows/${name}.yml`]) {
      const text = read(join(ROOT, where));
      assert.match(text, /^permissions:\n {2}contents: read\n(?! )/m, `${where} must set "permissions:" with "contents: read" alone at the top, so no job's token can write.`);
      assert.doesNotMatch(text, /:\s*write\b|write-all|read-all/, `${where} gives a token more than read access to the code.`);
      const uses = [...text.matchAll(/^ +(?:- )?uses: (.*)$/gm)].map((m) => m[1]);
      assert.ok(uses.length, `${where} uses no actions`);
      for (const action of uses) {
        assert.match(action, /^[\w.-]+\/[\w.\/-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$/, `${where}: "uses: ${action}" must name a full commit SHA with its version in a comment, such as actions/checkout@<40 hex digits> # v7.0.1. gh api repos/OWNER/REPO/commits/TAG gives the SHA.`);
      }
    }
  }
});

test("every command the workflow templates run is setup, the mutation run, or a check node check.mjs --list prints", () => {
  const listed = node("check.mjs", "--list");
  assert.equal(listed.status, 0, listed.output);
  const labels = lines(listed.output).filter(Boolean);
  const whole = new Set(["node setup.mjs", "node check.mjs", "node tools/mutate.mjs"]);
  for (const name of WORKFLOWS) {
    const commands = [...read(join(TEMPLATES, "workflows", `${name}.yml`)).matchAll(/^ +- run: (.+)$/gm)].map((m) => m[1]);
    assert.ok(commands.length, `${name}.yml runs nothing`);
    for (const command of commands) {
      if (whole.has(command)) continue;
      const script = command.match(/^node (tools\/[\w-]+\.mjs)( |$)/)?.[1];
      assert.ok(script && labels.some((label) => label.endsWith(`(${script})`)), `${name}.yml runs "${command}", which isn't a check node check.mjs --list prints.`);
    }
  }
});

test("the docs template runs on exactly the changes the ci template skips, and every job has a timeout", () => {
  const ci = read(join(TEMPLATES, "workflows", "ci.yml"));
  const docs = read(join(TEMPLATES, "workflows", "docs.yml"));
  const skipped = [...ci.matchAll(/^ {4}paths-ignore: (.+)$/gm)].map((m) => m[1]);
  const checked = [...docs.matchAll(/^ {4}paths: (.+)$/gm)].map((m) => m[1]);
  assert.equal(skipped.length, 2, "ci.yml should skip the same paths on push and on pull_request");
  assert.deepEqual(checked, skipped, "docs.yml must run on exactly what ci.yml skips, or a check is skipped with the work");
  for (const name of WORKFLOWS) {
    const jobs = (read(join(TEMPLATES, "workflows", `${name}.yml`)).split(/^jobs:\n/m)[1] ?? "").split(/^(?= {2}[\w-]+:\n)/m).filter((job) => job.trim());
    assert.ok(jobs.length, `${name}.yml has no jobs`);
    for (const job of jobs) assert.match(job, /^ {4}timeout-minutes: \d+$/m, `${name}.yml: job ${job.split(":")[0].trim()} has no timeout-minutes`);
  }
});

// --- The custom lint rule (chapter 17) ----------------------------------------------------------

const LINT = join(TEMPLATES, "lint_rule.py");
const summary = (output) => output.match(/checked \d+ files: .*/)?.[0];

test("the lint rule template agrees with the lab's own rule on the lab's code", () => {
  const template = python([LINT]);
  const lab = python(["-m", "helpdesk_lint"]);
  assert.equal(template.status, 0, template.output);
  assert.equal(lab.status, 0, lab.output);
  assert.ok(summary(template.output), template.output);
  assert.equal(summary(template.output), summary(lab.output));
  const exceptions = (output) => lines(output).filter((line) => line.startsWith("  exception at "));
  assert.deepEqual(exceptions(template.output), exceptions(lab.output));
});

test("the lint rule template fails a planted read with the fix in its message, and keeps exceptions honest", () => {
  const root = folder({
    "bad.py": 'def summarize(model):\n    response = model.complete(system="s", messages=[], tools=[])\n    return response.text.strip()\n',
    "mixed.py":
      'def ok(model, block):\n    response = model.complete(system="s", messages=[], tools=[])\n' +
      "    kept = response.text  # HDK101: kept for the transcript\n    # HDK101\n    again = response.text\n" +
      "    return block.text, kept, again  # HDK101: no longer needed\n",
  });
  const { status, output } = python([LINT, "."], root);
  assert.equal(status, 1, output);
  assert.match(output, /^bad\.py:3:12: HDK101 Read the model's text with final_text\(response\), not response\.text\./m);
  assert.match(output, /put the reason on it: # HDK101: <why>/);
  assert.match(output, /^mixed\.py:4:1: HDK102 /m);
  assert.match(output, /^mixed\.py:6:1: HDK103 /m);
  assert.doesNotMatch(output, /block/);
  assert.match(output, /checked 2 files: 3 problem\(s\), 1 exception\(s\)\./);
  assert.match(output, /exception at mixed\.py:3: kept for the transcript/);
});

test("the lint rule template follows a response under another name, as the lab's rule does", () => {
  // The lab's rule learned these forms after a review (2026-09-26); the template, a separate copy,
  // passed every one of them until it learned them too.
  const call = 'model.complete(system="s", messages=[])';
  const root = folder({
    "alias.py": `def f(model):\n    response = ${call}\n    r = response\n    return r.text\n`,
    "alias_of_alias.py": `def f(model):\n    a = ${call}\n    b = a\n    c: X = b\n    return c.text\n`,
    "walrus.py": `def f(model):\n    if (r := ${call}):\n        return r.text\n`,
    "walrus_read_at_once.py": `def f(model):\n    return (r := ${call}).text\n`,
    "tuple.py": `def f(model):\n    r, n = ${call}, 1\n    return r.text\n`,
    "nested_tuple.py": `def f(model):\n    [(r, n), m] = (${call}, 1), 2\n    return r.text\n`,
    // The other names in the same statement hold no response.
    "others.py": `def f(model, page):\n    r, n = ${call}, page\n    return final_text(r) + n.text\n`,
  });
  const found = (output) => lines(output).filter((line) => / HDK10\d /.test(line)).map((line) => line.split(": ")[0]);
  const template = python([LINT, "."], root);
  const lab = python(["-m", "helpdesk_lint", "."], root);
  assert.equal(template.status, 1, template.output);
  assert.deepEqual(found(template.output), [
    "alias.py:4:12",
    "alias_of_alias.py:5:12",
    "nested_tuple.py:3:12",
    "tuple.py:3:12",
    "walrus.py:3:16",
    "walrus_read_at_once.py:2:12",
  ]);
  assert.deepEqual(found(template.output), found(lab.output));
  assert.match(template.output, /checked 7 files: 6 problem\(s\), 0 exception\(s\)\./);
});

test("the lint rule template refuses a folder with no Python files, rather than pass it", () => {
  const { status, output } = python([LINT, "."], folder({ "notes.txt": "nothing to lint\n" }));
  assert.equal(status, 2, output);
  assert.match(output, /so nothing was checked/);
});

// --- The fitness test (chapter 15) --------------------------------------------------------------

test("the fitness test template passes on the lab's routes, and catches its planted violations", () => {
  const { status, output } = python(["-m", "pytest", "-q", "-p", "no:cacheprovider", "test_fitness.py"], TEMPLATES);
  assert.equal(status, 0, output);
  assert.match(output, /\b6 passed\b/);
});

// --- The judge's rubric (chapter 22) ------------------------------------------------------------

const LOAD_RUBRIC = [
  "import sys",
  "from pathlib import Path",
  "from helpdesk.assistant.judging import load_rubric, request",
  "rubric = load_rubric(Path(sys.argv[1]))",
  "for c in rubric.criteria:",
  '    message = request(rubric, c, "Hello Ben.", ["a passage the writer was given"])',
  "    assert c.question in message and rubric.given in message, c.id",
  'print(f"{len(rubric.criteria)} criteria, each builds a judge\'s request.")',
].join("\n");

test("the rubric template loads with the judge's own loader, and builds a judge's request for each criterion", () => {
  const { status, output } = python(["-c", LOAD_RUBRIC, join(TEMPLATES, "rubric.json")]);
  assert.equal(status, 0, output);
  assert.match(output, /2 criteria, each builds a judge's request\./);
});

test("a rubric with a misspelled field is refused by the same loader", () => {
  const broken = read(join(TEMPLATES, "rubric.json")).replace('"fail": "it states', '"fails": "it states');
  const root = folder({ "rubric.json": broken });
  const { status, output } = python(["-c", LOAD_RUBRIC, join(root, "rubric.json")]);
  assert.equal(status, 1, output);
  assert.match(output, /unknown field\(s\) fails; missing fail/);
});

// --- The Zero to Prod kit: Ask, Agree, Ship, Prove ---------------------------------------------
// Every test below starts "kit: " and needs only Node, so .github/workflows/docs.yml runs them when
// a change touches nothing but Markdown, the kit's own documents included.

const KIT = (...args) => node("tools/kit.mjs", ...args);
const LOCK = (...args) => node("tools/features-lock.mjs", ...args);
const PLACEHOLDER_PROBLEM = /is still a placeholder\. Replace it/;
const problemsIn = (output) => lines(output).filter((line) => line.startsWith("- "));

// A skeleton, checked as it stands, fails for its placeholders and nothing else.
function onlyPlaceholders({ status, output }) {
  assert.equal(status, 1, output);
  const problems = problemsIn(output);
  assert.ok(problems.length > 0, output);
  const other = problems.filter((p) => !PLACEHOLDER_PROBLEM.test(p));
  assert.deepEqual(other, [], "a skeleton should fail only for its placeholders");
}

const DOCS = [
  ["ask", "intake-brief"],
  ["agree", "project-spec"],
  ["ship", "handoff"],
  ["ship", "change-record"],
  ["ship", "release-card"],
  ["ship", "runbook"],
];

test("kit: each document's filled example passes against its skeleton, and the skeleton fails only for its placeholders", () => {
  for (const [stage, name] of DOCS) {
    const skeleton = `templates/${stage}/${name}.md`;
    const example = KIT("doc", skeleton, `templates/${stage}/${name}.example.md`);
    assert.equal(example.status, 0, `${name}: ${example.output}`);
    assert.match(example.output, /No problems found\./);
    onlyPlaceholders(KIT("doc", skeleton, skeleton));
  }
});

test("kit: a filled document with a section missing, emptied or left a placeholder fails", () => {
  const skeleton = "templates/ship/change-record.md";
  const example = read(join(TEMPLATES, "ship", "change-record.example.md"));
  const cases = [
    [example.replace(/## Rollback\n\n[^\n]+\n\n/, ""), /the section "## Rollback" is missing or out of order/],
    [example.replace(/## Dry run\n\n[^\n]+\n/, "## Dry run\n\n<!-- to do -->\n"), /"## Dry run" says nothing/],
    [example.replace("Revert the commit.", "<the steps that undo it>"), /"<the steps that undo it>" is still a placeholder/],
  ];
  for (const [text, message] of cases) {
    const root = folder({ "record.md": text });
    const run = KIT("doc", skeleton, join(root, "record.md"));
    assert.equal(run.status, 1, run.output);
    assert.match(run.output, message);
  }
});

test("kit: the intake brief asks chapter 28's intake questions, and has room for three from the gap check", () => {
  const brief = read(join(TEMPLATES, "ask", "intake-brief.md"));
  const rubric = read(join(PYTHON_DIR, "usecases", "rubric.toml"));
  const asks = [...rubric.matchAll(/^ask = "(.+)"$/gm)].map((m) => m[1]);
  assert.equal(asks.length, 3, rubric);
  for (const ask of asks) assert.ok(brief.includes(`- ${ask} <`), `the brief doesn't ask "${ask}"`);
  const followUps = brief.split("## Follow-up questions from the gap check")[1] ?? "";
  assert.equal([...followUps.matchAll(/^\d\. </gm)].length, 3);
});

test("kit: the runbook's later sections wait for their stage, and a runbook moved on must fill them", () => {
  const example = read(join(TEMPLATES, "ship", "runbook.example.md"));
  assert.match(example, /^\*\*Stage:\*\* Beta$/m);
  const moved = folder({ "runbook.md": example.replace("**Stage:** Beta", "**Stage:** Production") });
  const run = KIT("doc", "templates/ship/runbook.md", join(moved, "runbook.md"));
  assert.equal(run.status, 1, run.output);
  assert.equal(problemsIn(run.output).length, 3, run.output);
  assert.ok(problemsIn(run.output).every((p) => PLACEHOLDER_PROBLEM.test(p)), run.output);
});

test("kit: the gap list's example is decided throughout, and its skeleton fails only for its placeholders", () => {
  const example = KIT("decisions", "templates/ask/gaps.example.json", "--decided");
  assert.equal(example.status, 0, example.output);
  assert.match(example.output, /6 gap\(s\): 6 decided, 0 open\./);
  onlyPlaceholders(KIT("decisions", "templates/ask/gaps.json"));
  const record = JSON.parse(read(join(TEMPLATES, "ask", "gaps.example.json")));
  Object.assign(record.gaps[0], { decision: null, by: null, on: null });
  const root = folder({ "gaps.json": JSON.stringify(record) });
  const open = KIT("decisions", join(root, "gaps.json"), "--decided");
  assert.equal(open.status, 1, open.output);
  assert.match(open.output, /1 gap\(s\) still open \(G1\)/);
});

test("kit: the locked spec's example passes its lock, with its states document up to date, and its skeleton fails only for its placeholders", () => {
  const example = LOCK("templates/agree/features.example.json");
  assert.equal(example.status, 0, example.output);
  assert.match(example.output, /Done 5, in progress 0, to do 0, dropped 1\./);
  onlyPlaceholders(LOCK("templates/agree/features.json"));
  // Every decision the example rests on is the example gap list's, decided.
  const spec = JSON.parse(read(join(TEMPLATES, "agree", "features.example.json")));
  const gaps = new Map(JSON.parse(read(join(TEMPLATES, "ask", "gaps.example.json"))).gaps.map((g) => [g.id, g]));
  for (const f of spec.features) assert.ok(gaps.get(f.decision)?.decision, f.id);
});

test("kit: a feature with no test fails the lock", () => {
  const root = join(base, `case-${++n}`);
  cpSync(TEMPLATES, join(root, "templates"), { recursive: true });
  const path = join(root, "templates", "agree", "features.example.json");
  const spec = JSON.parse(read(path));
  spec.features[0].proof = null;
  writeFileSync(path, JSON.stringify(spec));
  const run = node("tools/features-lock.mjs", path, "--root", ROOT);
  assert.equal(run.status, 1, run.output);
  assert.match(run.output, /F1: has no proof test/);
});

test("kit: the lab's own skill is the skill template filled in, and loads", () => {
  const lab = KIT("skill", ".claude/skills/add-a-guard");
  assert.equal(lab.status, 0, lab.output);
  onlyPlaceholders(KIT("skill", "templates/ship/skills/your-skill-name"));
  // The reference quotes an entry from the lab's list, so it can't describe one that isn't there.
  const reference = read(join(ROOT, ".claude", "skills", "add-a-guard", "references", "mutation-entry.md"));
  const quoted = /```js\n([\s\S]*?)```/.exec(reference)[1].trim();
  const indented = quoted.split("\n").map((line) => `  ${line}`).join("\n");
  assert.ok(read(join(ROOT, "tools", "mutations.mjs")).includes(indented), "the reference's entry isn't in tools/mutations.mjs");
});

const HOOKS = join(TEMPLATES, "ship", "hooks");
const json = (path) => JSON.parse(read(path));

test("kit: the settings template is the guard's piece and the Stop hook's piece together, and the lab's own settings", () => {
  const guard = json(join(HOOKS, "guard.json"));
  const stop = json(join(HOOKS, "stop.json"));
  const merged = { permissions: guard.permissions, hooks: { ...guard.hooks, ...stop.hooks } };
  assert.deepEqual(json(join(HOOKS, "settings.json")), merged);
  assert.deepEqual(json(join(ROOT, ".claude", "settings.json")), merged);
  // Every script the settings run exists where they say.
  for (const entries of Object.values(merged.hooks)) {
    for (const hook of entries.flatMap((e) => e.hooks)) {
      assert.equal(hook.command, "node");
      const script = hook.args[0].replace("${CLAUDE_PROJECT_DIR}", ROOT);
      assert.ok(existsSync(script), script);
    }
  }
});

// Runs a hook the way its piece of the settings says, with CLAUDE_PROJECT_DIR the lab's root.
function wired(piece, event, input, env = {}) {
  const hook = json(join(HOOKS, piece)).hooks[event][0].hooks[0];
  const args = hook.args.map((a) => a.replace("${CLAUDE_PROJECT_DIR}", ROOT));
  const run = spawnSync(hook.command, args, { input: JSON.stringify(input), encoding: "utf8", env: { ...ENV, CLAUDE_PROJECT_DIR: ROOT, ...env } });
  return { status: run.status, stdout: run.stdout, stderr: run.stderr };
}
const pre = (permission_mode, command) => ({ hook_event_name: "PreToolUse", permission_mode, tool_name: "Bash", tool_input: { command } });
const decision = (run) => (run.stdout ? JSON.parse(run.stdout).hookSpecificOutput.permissionDecision : "none");

test("kit: the guard's wiring runs the lab's guard, which denies, asks and lets through by the rules", () => {
  const deny = wired("guard.json", "PreToolUse", pre("bypassPermissions", "git reset --hard HEAD~1"));
  assert.equal(deny.status, 0);
  assert.equal(decision(deny), "deny");
  assert.equal(decision(wired("guard.json", "PreToolUse", pre("default", "rm -rf build"))), "ask");
  assert.equal(decision(wired("guard.json", "PreToolUse", pre("bypassPermissions", "git status"))), "none");
});

test("kit: the guard's rules template is the lab's rules file, trimmed, and works in the lab's guard", () => {
  const template = read(join(HOOKS, "guard-rules.mjs"));
  const real = lines(read(join(ROOT, "tools", "hooks", "guard-rules.mjs")));
  let at = 0;
  for (const line of lines(template).filter((l) => l.trim() && !l.trim().startsWith("//"))) {
    const found = real.indexOf(line, at);
    assert.ok(found >= 0, `templates/ship/hooks/guard-rules.mjs: "${line.trim()}" isn't in tools/hooks/guard-rules.mjs after line ${at}.`);
    at = found + 1;
  }
  // The lab's guard, beside the template's rules, as a reader would put them.
  const root = folder({ "guard-rules.mjs": template });
  copyFileSync(join(ROOT, "tools", "hooks", "destructive-guard.mjs"), join(root, "destructive-guard.mjs"));
  const guard = (input) =>
    decision(spawnSync(process.execPath, [join(root, "destructive-guard.mjs")], { input: JSON.stringify(input), encoding: "utf8" }));
  assert.equal(guard(pre("bypassPermissions", "rm -rf build")), "deny");
  assert.equal(guard(pre("dontAsk", "git push --force origin main")), "deny");
  assert.equal(guard(pre("default", "git reset --hard")), "ask");
  assert.equal(guard(pre("bypassPermissions", "bash -c 'rm -rf build'")), "deny");
  assert.equal(guard(pre("bypassPermissions", "git status")), "none");
  // A rules file that won't load denies, as the lab's does.
  writeFileSync(join(root, "guard-rules.mjs"), `${template}\nthis is not JavaScript\n`);
  assert.equal(guard(pre("default", "git status")), "deny");
});

test("kit: the Stop hook's wiring runs the lab's hook, which sends a failing check back", () => {
  const project = folder({
    "check.mjs": 'console.log("FAIL  Stub tests (0.2s)\\n      expected 2, got 3\\n\\n1 of 1 checks failed.");\nprocess.exit(1);\n',
  });
  const state = folder({ ".keep": "" });
  const input = { session_id: "kit", hook_event_name: "Stop", stop_hook_active: false, cwd: project };
  const run = wired("stop.json", "Stop", input, { LAB_HOOK_STATE_DIR: state });
  assert.equal(run.status, 2, run.stderr);
  assert.match(run.stderr, /^The fast checks failed, so the work isn't finished \(round 1 of 3\)\./);
});

test("kit: the changelog convention is what the check holds the lab's own changelog to", () => {
  const convention = read(join(TEMPLATES, "ship", "CHANGELOG-convention.md"));
  for (const rule of ["`# Changelog`", "`## YYYY-MM-DD, what changed`, newest first", "at least one bullet"]) {
    assert.ok(convention.includes(rule), rule);
  }
  const lab = KIT("changelog", "CHANGELOG.md");
  assert.equal(lab.status, 0, lab.output);
});

test("kit: the claims example is measured as its proof page says, and its skeleton is refused for its placeholders", () => {
  const out = join(base, `proof-${++n}.md`);
  const run = node("tools/claims.mjs", "templates/prove/claims.example.json", "--out", out);
  // The example keeps one claim nothing measures yet, and an unknown fails the run.
  assert.equal(run.status, 1, run.output);
  assert.match(run.output, /4 of 5 claim\(s\) hold\./);
  assert.match(run.output, /^UNKNOWN {2}real-model: no command measures it yet$/m);
  // The committed page is what the script writes, apart from when and at which commit.
  const when = (text) =>
    text.replace(/^Measured .*?, at .*?\. (\d+ claim)/m, "Measured WHEN, at COMMIT. $1").replace(/\| \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC \|/g, "| WHEN |");
  assert.equal(when(read(out)), when(read(join(TEMPLATES, "prove", "proof.example.md"))));
  onlyPlaceholders(node("tools/claims.mjs", "templates/prove/claims.json", "--out", join(base, "never.md")));
  assert.equal(existsSync(join(base, "never.md")), false);
});

test("kit: every file the kit's README names is in the repository", () => {
  const readme = read(join(TEMPLATES, "README.md"));
  const named = [...readme.matchAll(/`((?:templates|tools|python|progress|\.claude|\.github)\/[^`\s]+|AGENTS\.md|CLAUDE\.md|CHANGELOG\.md|LICENSE)`/g)].map((m) => m[1]);
  assert.ok(named.length > 30, named.join("\n"));
  for (const path of named) assert.ok(existsSync(join(ROOT, path)), path);
  assert.match(readme, /MIT-licensed, like the rest of this repository/);
});

test("kit: a change to Markdown alone still runs the kit's tests, in docs.yml", () => {
  const docs = read(join(ROOT, ".github", "workflows", "docs.yml"));
  assert.match(docs, /^ {6}- run: node --test --test-name-pattern "\^kit:" tools\/templates\.test\.mjs$/m);
  // Every test that line runs needs only Node: none of them may start Python.
  const source = read(fileURLToPath(import.meta.url));
  for (const [, name, body] of source.matchAll(/^test\("(kit: [^"]+)", (?:async )?\(\) => \{\n([\s\S]*?)^\}\);$/gm)) {
    assert.doesNotMatch(body, /\bpython\(/, `${name} starts Python, which docs.yml doesn't install`);
  }
});
