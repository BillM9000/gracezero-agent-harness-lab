// Tests for the destructive-command guard (tools/hooks/destructive-guard.mjs and guard-rules.mjs,
// chapter 19). Every command here is data, fed to the guard the way Claude Code would feed it: none
// of them is ever run.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { ASK_MODES, classify, decide } from "./guard-rules.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const LAB = resolve(HERE, "..", "..");
const GUARD = join(HERE, "destructive-guard.mjs");
const ids = (command) => classify(command).map((rule) => rule.id);
const input = (permission_mode, command, tool_name = "Bash") => ({
  hook_event_name: "PreToolUse",
  permission_mode,
  tool_name,
  tool_input: { command },
});

// Runs the guard the way Claude Code does: its input on stdin, in its own process.
function guard(stdin, script = GUARD, args = []) {
  const run = spawnSync(process.execPath, [script, ...args], { input: stdin, encoding: "utf8" });
  return { code: run.status, stdout: run.stdout, stderr: run.stderr };
}

test("each destructive command is caught, in bash, PowerShell, through a shell and past git's options", () => {
  const cases = [
    ["rm -rf build", "delete-files"],
    ["cd python && rm .run/helpdesk.db", "delete-files"],
    ["/bin/rm -rf build", "delete-files"],
    ["ls *.log | xargs rm", "delete-files"],
    ["FORCE=1 rm notes.txt", "delete-files"],
    ["Remove-Item -Recurse python/.run", "delete-files-powershell"],
    ["find . -name '*.db' -delete", "find-delete"],
    ["find . -name '*.db' -exec rm {} +", "find-delete"],
    ["git reset --hard HEAD~1", "git-reset-hard"],
    ["git -C ../lab reset --hard", "git-reset-hard"],
    ["git clean -fdx", "git-clean"],
    ["git checkout -- python/src", "git-discard"],
    ["git checkout .", "git-discard"],
    ["git restore python/src/helpdesk/triage.py", "git-discard"],
    ["git restore --staged --worktree README.md", "git-discard"],
    ["git branch -D old-idea", "git-branch-delete"],
    ["git push --force", "git-force-push"],
    ["git push origin main --force", "git-force-push"],
    ["git -C . push -f origin main", "git-force-push"],
    ["git push origin +main", "git-force-push"],
    ["git push --force-with-lease=main origin", "git-force-push"],
    ["git stash drop", "git-stash-drop"],
    ["git filter-repo --path secrets.txt --invert-paths", "git-rewrite"],
    ["bash -c 'git reset --hard'", "git-reset-hard"],
    ['pwsh -Command "Remove-Item -Recurse build"', "delete-files-powershell"],
    ["bash <<'EOF'\ncd python\nrm -rf .venv\nEOF", "delete-files"],
    ['sqlite3 python/.run/helpdesk.db "DELETE FROM proposals"', "sql-delete-all"],
    ["sqlite3 helpdesk.db 'DROP TABLE approval_log'", "sql-drop"],
  ];
  for (const [command, id] of cases) {
    assert.ok(ids(command).includes(id), `${JSON.stringify(command)} should break ${id}, got [${ids(command)}]`);
  }
});

test("everyday commands pass, including ones that only mention a destructive command", () => {
  const safe = [
    "git status",
    "git log --oneline -5",
    "git diff HEAD~1",
    "git push origin main",
    "git push -u origin chapter-19",
    "git branch -d merged-branch",
    "git checkout -b chapter-19",
    "git checkout main",
    "git restore --staged README.md",
    "git stash",
    "git clean -n",
    "node check.mjs",
    "grep -rn 'rm -rf' tools",
    'git commit -m "Say why git reset --hard needs a person"',
    "git commit -F - <<'EOF'\nStop an agent running rm -rf or git push --force.\nEOF",
    "cat > notes.md <<'EOF'\nrm -rf and git clean -fdx are never run here.\nEOF",
    'echo "checks passed; rm -rf is not needed"',
    // A script's text is code, not a shell command. The guard can't see what a script does.
    `node -e "console.log('never run git reset --hard here')"`,
    'sqlite3 python/.run/helpdesk.db "DELETE FROM proposals WHERE id = 3"',
    'echo "DROP TABLE tickets" > example.sql',
  ];
  for (const command of safe) assert.deepEqual(ids(command), [], `${JSON.stringify(command)} is not destructive`);
});

test("where a person can see a prompt the guard asks; where none can be shown it denies and says why", () => {
  for (const mode of ASK_MODES) {
    const { hookSpecificOutput } = decide(input(mode, "git reset --hard"));
    assert.equal(hookSpecificOutput.hookEventName, "PreToolUse");
    assert.equal(hookSpecificOutput.permissionDecision, "ask", `${mode} can show a prompt`);
  }
  assert.deepEqual([...ASK_MODES], ["default", "acceptEdits", "plan", "auto"]);
  for (const mode of ["bypassPermissions", "dontAsk", "a-mode-added-next-year", undefined]) {
    const { hookSpecificOutput } = decide(input(mode, "git reset --hard"));
    assert.equal(hookSpecificOutput.permissionDecision, "deny", `${mode} shows no prompt, so the guard denies`);
    assert.match(hookSpecificOutput.permissionDecisionReason, /throws away uncommitted work/);
    assert.match(hookSpecificOutput.permissionDecisionReason, /Tell the person the exact command/);
    assert.match(hookSpecificOutput.permissionDecisionReason, /Don't reword the command/);
  }
  assert.equal(decide(input("bypassPermissions", "git status")), null, "anything else is left to Claude Code");
  assert.equal(decide({ tool_name: "Read", tool_input: { file_path: "x" } }), null);
  assert.equal(decide(input("default", "Remove-Item build", "PowerShell")).hookSpecificOutput.permissionDecision, "ask");
});

test("a failure inside the guard denies the command instead of letting it through", () => {
  const broken = guard("{ this is not json");
  assert.equal(broken.code, 0, broken.stderr);
  const { hookSpecificOutput } = JSON.parse(broken.stdout);
  assert.equal(hookSpecificOutput.permissionDecision, "deny");
  assert.match(hookSpecificOutput.permissionDecisionReason, /^The destructive-command guard failed/);
});

test("the samples give the answers the book shows, and --mode replaces the input's mode", () => {
  const sample = join(HERE, "samples", "pre-tool-use.json");
  const asked = guard("", GUARD, ["--input", sample]);
  assert.equal(JSON.parse(asked.stdout).hookSpecificOutput.permissionDecision, "ask");
  const denied = guard("", GUARD, ["--input", sample, "--mode", "bypassPermissions"]);
  assert.equal(JSON.parse(denied.stdout).hookSpecificOutput.permissionDecision, "deny");
  const mention = guard("", GUARD, ["--input", join(HERE, "samples", "pre-tool-use-mention.json")]);
  assert.deepEqual(mention, { code: 0, stdout: "", stderr: "" });
});

// .claude/settings.json is what makes Claude Code run the guard. A mistyped path or a matcher that
// misses a shell fails nothing visible, so start the configured command the way Claude Code would.
test("the configured guard starts, covers both shells, and the deny rules are there", () => {
  const settings = JSON.parse(readFileSync(join(LAB, ".claude", "settings.json"), "utf8"));
  const group = settings.hooks.PreToolUse.find((g) => g.hooks.some((h) => h.args?.[0]?.endsWith("destructive-guard.mjs")));
  assert.ok(group, ".claude/settings.json has no PreToolUse hook running the guard");
  for (const tool of ["Bash", "PowerShell"]) {
    assert.ok(new RegExp(`^(?:${group.matcher})$`).test(tool), `the matcher "${group.matcher}" must cover ${tool}`);
  }
  const handler = group.hooks.find((h) => h.args[0].endsWith("destructive-guard.mjs"));
  assert.equal(handler.command, "node");
  const script = handler.args[0].replace("${CLAUDE_PROJECT_DIR}", LAB);
  assert.ok(existsSync(script), `${handler.args[0]} doesn't exist`);
  // A timed-out PreToolUse hook doesn't block the call, so a slow guard is no guard.
  assert.ok(handler.timeout <= 30, "keep the guard's timeout short");
  const stopped = guard(JSON.stringify(input("bypassPermissions", "git push origin main --force")), script);
  assert.equal(JSON.parse(stopped.stdout).hookSpecificOutput.permissionDecision, "deny");
  assert.equal(guard(JSON.stringify(input("bypassPermissions", "git status")), script).stdout, "");

  // Deny rules are Claude Code's own: they hold in every mode, even if the guard never starts. They
  // match the command's text from the start, so git push origin main --force slips past them; the
  // guard catches that form, as the test above shows.
  const deny = settings.permissions.deny;
  for (const rule of ["Bash(git push --force *)", "Bash(git push -f *)", "PowerShell(git push --force *)", "PowerShell(git push -f *)"]) {
    assert.ok(deny.includes(rule), `.claude/settings.json must deny ${rule}`);
  }
});
