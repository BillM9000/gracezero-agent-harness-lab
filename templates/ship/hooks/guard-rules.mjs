// TEMPLATE: the rules file of a destructive-command guard, for Claude Code's PreToolUse hook (Ship,
// Appendix B). The lab's tools/hooks/destructive-guard.mjs loads it from its own folder, and
// settings.json (beside this file) wires the guard to the Bash and PowerShell tools. This is the
// lab's tools/hooks/guard-rules.mjs with most of its rules left out: keep the code, and add a rule
// for each command that can lose work in your repository. tools/templates.test.mjs holds it to
// the lab's file, line for line, and runs the guard with it.
//
// "Destructive" here means a mistake that loses work no commit holds, or history someone else has.
// It reads the command's words, so it's a net, not a sandbox: it can't see what a script does once
// it starts, and a determined rewrite can get past any pattern. Its job is the ordinary case.

// Programs that run a quoted argument, or a heredoc, as a shell command: that text is read too.
const SHELLS = new Set(["bash", "sh", "zsh", "pwsh", "powershell", "cmd", "eval", "ssh"]);
// Programs that run SQL: their quoted text and heredocs are read for the SQL rules.
const SQL_CLIENTS = new Set(["sqlite3", "psql", "mysql"]);
// Words that run the rest of the line as the command.
const WRAPPERS = new Set(["sudo", "command", "env", "nohup", "time", "exec", "xargs"]);

// git's own options come before its subcommand: git -C path reset --hard.
function git(w) {
  let i = 1;
  while (i < w.length && w[i].startsWith("-")) i += ["-C", "-c"].includes(w[i]) ? 2 : 1;
  return { sub: w[i], rest: w.slice(i + 1) };
}
const has = (rest, ...flags) => rest.some((a) => flags.includes(a));
const shortFlag = (rest, letter) => rest.some((a) => /^-[a-zA-Z]+$/.test(a) && a.includes(letter));

// Each rule: what the command would destroy, in words for the person, and a test on one simple
// command's words, program first.
export const RULES = [
  { id: "delete-files", what: "deletes files", test: (w) => ["rm", "rmdir", "unlink", "shred"].includes(w[0]) },
  {
    id: "delete-files-powershell",
    what: "deletes files",
    test: (w) => ["remove-item", "ri", "del", "erase", "rd", "clear-content"].includes(w[0].toLowerCase()),
  },
  {
    id: "git-reset-hard",
    what: "throws away uncommitted work (git reset --hard)",
    test: (w) => w[0] === "git" && git(w).sub === "reset" && has(git(w).rest, "--hard"),
  },
  {
    id: "git-force-push",
    what: "overwrites history on a remote (a force push)",
    // Any word order: git push origin main --force is the same push as git push --force origin main.
    test: (w) => {
      if (w[0] !== "git" || git(w).sub !== "push") return false;
      const rest = git(w).rest;
      return (
        has(rest, "--force", "--force-with-lease") ||
        shortFlag(rest, "f") ||
        rest.some((a) => a.startsWith("--force-with-lease=") || /^\+\S/.test(a))
      );
    },
  },
  // TEMPLATE: a rule for each command that can lose work here, as { id, what, test }.
];

// Applied to the text a command hands to a SQL client.
export const SQL_RULES = [
  { id: "sql-drop", what: "drops a table or a database", test: (sql) => /\bDROP\s+(TABLE|DATABASE|SCHEMA)\b/i.test(sql) },
  { id: "sql-truncate", what: "empties a table", test: (sql) => /\bTRUNCATE\b/i.test(sql) },
  {
    id: "sql-delete-all",
    what: "deletes every row (DELETE with no WHERE)",
    test: (sql) => sql.split(";").some((s) => /\bDELETE\s+FROM\b/i.test(s) && !/\bWHERE\b/i.test(s)),
  },
];

// Splits one line into simple commands at ; && || | and &, outside quotes. Each command is a list of
// words; a quoted string stays one word, marked quoted, so its contents never read as flags.
export function simpleCommands(line) {
  const commands = [[]];
  let word = null;
  const end = () => {
    if (word) commands.at(-1).push(word);
    word = null;
  };
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "'" || c === '"') {
      const close = c === "'" ? line.indexOf("'", i + 1) : findClosingDouble(line, i + 1);
      const stop = close === -1 ? line.length : close;
      const text = line.slice(i + 1, stop);
      word = { text: (word?.text ?? "") + (c === '"' ? text.replace(/\\(.)/g, "$1") : text), quoted: true };
      i = stop;
    } else if (";&|".includes(c)) {
      end();
      if (line[i + 1] === c) i++; // && and ||
      commands.push([]);
    } else if (/\s/.test(c)) {
      end();
    } else {
      word = { text: (word?.text ?? "") + c, quoted: word?.quoted ?? false };
    }
  }
  end();
  return commands.filter((command) => command.length > 0);
}

function findClosingDouble(line, from) {
  for (let i = from; i < line.length; i++) {
    if (line[i] === "\\") i++;
    else if (line[i] === '"') return i;
  }
  return -1;
}

// The program's own name: /bin/rm and C:\Git\bin\git.exe are rm and git.
const programName = (text) => text.split(/[\\/]/).pop().replace(/\.exe$/i, "");

// Takes heredoc bodies out of the command line, so a commit message or a file written with cat
// isn't read as commands. Returns each remaining line with the body it feeds, if any.
export function lines(command) {
  const all = command.split(/\r?\n/);
  const out = [];
  for (let i = 0; i < all.length; i++) {
    const heredoc = /<<-?\s*(['"]?)([A-Za-z_]\w*)\1/.exec(all[i]);
    if (!heredoc) {
      out.push({ text: all[i], body: "" });
      continue;
    }
    let j = i + 1;
    while (j < all.length && all[j].trim() !== heredoc[2]) j++;
    out.push({ text: all[i], body: all.slice(i + 1, j).join("\n") });
    i = j;
  }
  return out;
}

// Every rule the command breaks; empty when it breaks none.
export function classify(command, depth = 0) {
  if (typeof command !== "string" || depth > 3) return [];
  const broken = [];
  for (const { text, body } of lines(command)) {
    for (const command of simpleCommands(text)) {
      let w = command;
      // Skip leading NAME=value assignments and wrappers, with any flags a wrapper takes.
      while (w.length && !w[0].quoted && (/^[A-Za-z_]\w*=/.test(w[0].text) || WRAPPERS.has(w[0].text))) {
        w = w.slice(1);
        while (w.length && !w[0].quoted && w[0].text.startsWith("-") && w.length > 1) w = w.slice(1);
      }
      if (!w.length) continue;
      const names = [programName(w[0].text), ...w.slice(1).map((x) => x.text)];
      broken.push(...RULES.filter((rule) => rule.test(names)));
      const handed = [...w.slice(1).filter((x) => x.quoted).map((x) => x.text), ...(body ? [body] : [])];
      if (SHELLS.has(names[0].toLowerCase())) {
        for (const inner of handed) broken.push(...classify(inner, depth + 1));
      }
      if (SQL_CLIENTS.has(names[0])) {
        broken.push(...SQL_RULES.filter((rule) => handed.some((sql) => rule.test(sql))));
      }
    }
  }
  return broken;
}

// Modes in which Claude Code can show the person a permission prompt, so the guard asks. In every
// other mode (bypassPermissions, dontAsk, or one this list doesn't know) it denies.
export const ASK_MODES = new Set(["default", "acceptEdits", "plan", "auto"]);

const answer = (permissionDecision, permissionDecisionReason) => ({
  hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision, permissionDecisionReason },
});

// The guard's answer for one PreToolUse input, or null to leave the call to Claude Code's own rules.
export function decide(input) {
  const command = input?.tool_input?.command;
  if (typeof command !== "string") return null;
  const broken = classify(command);
  if (broken.length === 0) return null;
  const what = [...new Set(broken.map((rule) => rule.what))].join("; ");
  const mode = input.permission_mode ?? "unknown";
  if (ASK_MODES.has(mode)) {
    return answer("ask", `This command ${what}. Approve it only if you meant it to (tools/hooks/destructive-guard.mjs).`);
  }
  return answer(
    "deny",
    `Stopped before it ran: this command ${what}, and in this permission mode (${mode}) no one is asked. ` +
      "Tell the person the exact command and why it's needed, and let them run it or switch to a mode that " +
      "asks. Don't reword the command to get past this check.",
  );
}

// What the guard answers when it fails: a deny, because Claude Code lets a tool call through when its
// hook crashes, times out or can't start.
export function failed(error) {
  return answer(
    "deny",
    `The destructive-command guard failed (${error?.message ?? error}), so it stopped this command rather ` +
      "than let it through unchecked. Tell the person, and fix tools/hooks/destructive-guard.mjs.",
  );
}
