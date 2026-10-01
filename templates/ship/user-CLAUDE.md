# User-level instructions: <whose machine>

<!-- Ship. The instruction file a coding agent loads in every project on one person's machine,
before the project's own CLAUDE.md or AGENTS.md. Claude Code reads it from ~/.claude/CLAUDE.md.
Other tools keep the same kind of file, as their documentation described them on 23 September
2026 (Appendix A): Codex CLI reads a global AGENTS.md before the project's, Cursor has user rules,
and Windsurf (Devin Desktop) a global rules file of up to 6,000 characters. Keep this file to what
holds in every project: it loads in every session, so every line costs every time. Check it with:
node tools/kit.mjs doc templates/ship/user-CLAUDE.md YOUR-FILE.md
and its size with node tools/instruction-files.mjs FOLDER --max-tokens 4000, on a folder that
holds only a copy of it, named CLAUDE.md. -->

**Machine:** <whose machine, its operating system and shell, and where its projects live>. **Read by:** <each coding agent that reads this file, and where its copy is>. **Last reviewed:** <YYYY-MM-DD>.

## What this file is

Loaded at the start of every session in every project on this machine, before the project's own instructions. Nothing here is about one project: each project's `AGENTS.md`, imported by its `CLAUDE.md`, holds its commands, layout and rules. Where a project's file says otherwise, follow it there, except on the invariants below, which a project's file can add to but not loosen.

<Anything every project here shares, such as the shell commands run in.>

## Invariants

1. **Verify; don't assume.** A handoff, a note, a ticket or an earlier session's summary is a claim. Check it against the code, a command's output or the running system before you act on it or repeat it.
2. **Say when something wasn't verified.** If you didn't check it this session, say so in the same sentence.
3. **Report outcomes as they are.** A failing check is reported as failing, with its output; a skipped step as skipped; half-finished work as half finished.
4. **Never write a secret anywhere.** Not in code, a commit, a log, a document or a reply. Refer to it by its name.
5. **A question is not an instruction.** When I ask whether something could or should be done, answer, and change nothing until I ask you to.
6. <An invariant of your own, only if it holds in every project.>

## Destructive operations

### The rule

Before any command whose failure is lost data or an outage rather than an error message, ask me in chat: name the command, what it would destroy, and how it could be undone, then wait for a clear yes. This holds in every permission mode. A tool's permission prompt doesn't count as asking, and in a mode that shows none, asking in chat is the only check left.

### One approval for a bounded job

When I ask for a job that destroys things by design, with clear edges, ask once at the start: list everything it will delete, drop or overwrite, then do those steps without asking at each one. Ask again if it turns out to need anything not on that list, or touches another project or something projects share.

### What counts

- Deleting files no commit holds, or overwriting them.
- In git: `reset --hard`, `clean`, throwing away uncommitted changes, deleting an unmerged branch, dropping a stash, a force push, rewriting history.
- In a database: dropping a table or a database, emptying a table, a `DELETE` with no `WHERE`, a migration that removes data.
- Stopping, restarting or removing a service or a scheduled job that someone else relies on.
- <Anything else on this machine that can lose work.>

When you can't tell, it counts.

## Secrets

- **Where they live:** <where secrets are kept on this machine, such as each project's git-ignored .env file, or the system's keychain>.
- Refer to a secret by its variable's name, never its value.
- Never run a command that would print one. To see which variables a file sets, list the names alone.
- If you come across a secret in a file, a log or a command's output, stop, tell me where, and don't repeat it.

## How to report

- **Done** means <what done means in every project, such as: the change is made, the project's full checks pass, and it's committed>.
- Each claim comes with its evidence: the command you ran and what it showed.
- Say what you skipped or didn't run, and why.

## Hooks

<!-- Hooks have a user level too, as the tools' documentation described it on 30 September 2026
(Appendix A): Claude Code reads hooks from ~/.claude/settings.json in every project, Codex CLI from
your home folder, each one reviewed and trusted before it runs, and Cursor from
~/.cursor/hooks.json. Copilot CLI, Cursor and the Devin CLI also
read the hooks in a repository's .claude/settings.json. The kit's destructive-command guard
(templates/ship/hooks/guard.json, with guard-rules.mjs) suits the user level: in your user
settings, point it at a copy in your home folder instead of ${CLAUDE_PROJECT_DIR}. The kit's Stop
hook (templates/ship/hooks/stop.json) runs a project's own fast checks, so wire it in each
project. -->

- <Each hook that runs in every project, what it does, and the file that wires it.>
- When a hook stops a command, don't look for another way to run it: ask me in chat, naming the command.

## Starting a session

1. Read the project's `CLAUDE.md` and what it imports, before anything else.
2. Read its handoff or session log, if it has one (<where projects here keep it>), and treat every status in it as a claim to check.
3. Check the state you'd build on before you change anything: `git status`, the recent history and the project's checks.
4. Tell me what's done and what isn't, with the command behind each, before you start.

## Keeping this file small

- **Budget:** <a line and token budget, such as 120 lines and 3,000 estimated tokens>, under the kit's 200 lines and 4,000 estimated tokens.
- A rule that matters in one project moves to that project's `AGENTS.md`. A procedure needed only sometimes becomes a skill. A rule a hook can enforce becomes a hook, with a line here saying so.
- <When it's reviewed, and who may change it.>
