// Claude Code's PreToolUse hook on the Bash and PowerShell tools (chapter 19), wired up in
// .claude/settings.json: before a shell command runs, hold back one that would destroy work no
// commit holds (tools/hooks/guard-rules.mjs has the list).
//
// It reads the hook's JSON input on stdin, or from --input <file> when you try it by hand, and
// always exits 0, answering in JSON on stdout as Claude Code's hooks reference describes:
//   - nothing for a command that isn't destructive, so Claude Code's own rules and mode decide;
//   - "ask" where Claude Code can show the person a permission prompt: Manual (default),
//     acceptEdits, plan and auto;
//   - "deny", with the reason, in bypassPermissions, dontAsk or a mode it doesn't know. The
//     documentation says a hook's deny blocks even in bypassPermissions; it doesn't say what a hook's
//     "ask" does there, so the guard doesn't rely on it.
// A failure inside the guard denies too, including a rules file that won't load, which is why the
// rules are imported inside the try rather than at the top: a static import that fails ends the
// process with exit 1 and no answer, and Claude Code treats that as a non-blocking error and runs
// the command. What the guard can't answer for is itself: a hook that times out, or that can't
// start at all (node missing, a mistyped path in the settings), still lets the command through, so
// the guard has to be quick, and the deny rules in .claude/settings.json hold without it.
// --mode <mode> replaces the input's permission_mode, for trying it by hand.
import { readFileSync } from "node:fs";

// The answer when the guard fails. guard-rules.mjs has failed() for this, but when that file is the
// one that won't load, its failed() can't load either, so the same deny is built here.
function deny(error) {
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason:
        `The destructive-command guard failed (${error?.message ?? error}), so it stopped this command rather ` +
        "than let it through unchecked. Tell the person, and fix tools/hooks/destructive-guard.mjs.",
    },
  };
}

let out;
let rules;
try {
  rules = await import("./guard-rules.mjs");
  const at = process.argv.indexOf("--input");
  const input = JSON.parse(readFileSync(at > 0 ? process.argv[at + 1] : 0, "utf8"));
  const mode = process.argv.indexOf("--mode");
  if (mode > 0) input.permission_mode = process.argv[mode + 1];
  out = rules.decide(input);
} catch (error) {
  try {
    out = rules.failed(error);
  } catch {
    out = deny(error);
  }
}
if (out) process.stdout.write(`${JSON.stringify(out)}\n`);
process.exit(0);
