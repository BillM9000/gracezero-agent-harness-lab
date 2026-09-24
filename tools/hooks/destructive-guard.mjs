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
// A failure inside the guard denies too, because Claude Code lets a call through when its hook
// crashes. --mode <mode> replaces the input's permission_mode, for trying it by hand.
import { readFileSync } from "node:fs";
import { decide, failed } from "./guard-rules.mjs";

let out;
try {
  const at = process.argv.indexOf("--input");
  const input = JSON.parse(readFileSync(at > 0 ? process.argv[at + 1] : 0, "utf8"));
  const mode = process.argv.indexOf("--mode");
  if (mode > 0) input.permission_mode = process.argv[mode + 1];
  out = decide(input);
} catch (error) {
  out = failed(error);
}
if (out) process.stdout.write(`${JSON.stringify(out)}\n`);
process.exit(0);
