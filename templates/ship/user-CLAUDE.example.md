# User-level instructions: my work laptop

<!-- A filled example of templates/ship/user-CLAUDE.md: the user-level file of an invented
engineer, kept at ~/.claude/CLAUDE.md, for a laptop with two invented projects. Nothing in it is
about either project; their own files hold that. -->

**Machine:** my work laptop, Ubuntu 24.04 with bash; two projects, `~/src/orchard-api` and `~/src/orchard-app`, each a git repository. **Read by:** Claude Code, from `~/.claude/CLAUDE.md`, and Codex CLI, whose global `AGENTS.md` is a copy of this file. **Last reviewed:** 2026-09-30.

## What this file is

Loaded at the start of every session in every project on this machine, before the project's own instructions. Nothing here is about one project: each project's `AGENTS.md`, imported by its `CLAUDE.md`, holds its commands, layout and rules. Where a project's file says otherwise, follow it there, except on the invariants below, which a project's file can add to but not loosen.

Commands run in bash. Use `python3`, not `python`, and a project's own virtual environment when it has one.

## Invariants

1. **Verify; don't assume.** A handoff, a note, a ticket or an earlier session's summary is a claim. Check it against the code, a command's output or the running system before you act on it or repeat it.
2. **Say when something wasn't verified.** If you didn't check it this session, say so in the same sentence: "the handoff says the export job is fixed; I haven't run it."
3. **Report outcomes as they are.** A failing check is reported as failing, with its output; a skipped step as skipped; half-finished work as half finished.
4. **Never write a secret anywhere.** Not in code, a commit, a log, a document or a reply. Refer to it by its name.
5. **A question is not an instruction.** When I ask whether something could or should be done, answer, and change nothing until I ask you to.
6. **Never push.** Commit when the work is done; I push once I've read the diff.

## Destructive operations

### The rule

Before any command whose failure is lost data or an outage rather than an error message, ask me in chat: name the command, what it would destroy, and how it could be undone, then wait for a clear yes. This holds in every permission mode. A tool's permission prompt doesn't count as asking, and in a mode that shows none, asking in chat is the only check left.

### One approval for a bounded job

When I ask for a job that destroys things by design, with clear edges, ask once at the start: list everything it will delete, drop or overwrite, then do those steps without asking at each one. Ask again if it turns out to need anything not on that list, or touches another project or something projects share. "Rebuild the search index from scratch" is one approval for deleting the index and building it again; finding that the rebuild also empties a cache the other project reads is a new question.

### What counts

- Deleting files no commit holds, or overwriting them.
- In git: `reset --hard`, `clean`, throwing away uncommitted changes, deleting an unmerged branch, dropping a stash, a force push, rewriting history.
- In a database: dropping a table or a database, emptying a table, a `DELETE` with no `WHERE`, a migration that removes data.
- Stopping, restarting or removing a service or a scheduled job that someone else relies on.
- Stopping the local database server, or deleting its data folder: both projects keep their development data in it.

When you can't tell, it counts.

## Secrets

- **Where they live:** each project's `.env` file, which git ignores, and the system keyring for anything both projects use.
- Refer to a secret by its variable's name, such as `PAYMENTS_API_KEY`, never its value.
- Never run a command that would print one: no `cat .env`, no `env` or `printenv`, no `echo` of a secret's variable. To see which variables a file sets, run `cut -d= -f1 .env`.
- If you come across a secret in a file, a log or a command's output, stop, tell me where, and don't repeat it.

## How to report

- **Done** means the change is made, the project's full checks pass, its changelog says what changed and why, and it's committed. Anything less is reported as what it is.
- Each claim comes with its evidence: the command you ran and what it showed, such as "`make check`: 212 passed, 0 failed".
- Say what you skipped or didn't run, and why.
- Start with the outcome, in a sentence or two; the details come after.

## Hooks

- `~/.claude/settings.json` runs the kit's destructive-command guard, kept in `~/agent-guards/`, before every shell command in every project, and its deny rules stop force pushes. The guard asks where Claude Code can show me a prompt, and denies where it can't.
- Codex CLI runs the same guard from its hooks file in my home folder, with `--mode dontAsk`: its documentation (30 September 2026) says it doesn't support a hook's ask yet, and would run the command. It runs a hook only once I've reviewed and trusted it.
- Each project wires its own Stop hook, in its `.claude/settings.json`, because the hook runs that project's fast checks.
- When a hook stops a command, don't look for another way to run it: ask me in chat, naming the command, and if I agree I'll run it myself.

## Starting a session

1. Read the project's `CLAUDE.md` and what it imports, before anything else.
2. Read its handoff, `docs/handoff.md` in both projects, and treat every status in it as a claim to check.
3. Check the state you'd build on before you change anything: `git status`, `git log --oneline -10` and the project's fast checks.
4. Tell me what's done and what isn't, with the command behind each, before you start.

## Keeping this file small

- **Budget:** 120 lines and 3,000 estimated tokens, under the kit's 200 lines and 4,000 estimated tokens. It loads in every session of every project, so each line costs every time.
- A rule that matters in one project moves to that project's `AGENTS.md`: running the migrations before the tests moved to `orchard-api`'s on 2026-08-14. A procedure needed only sometimes becomes a skill. A rule a hook can enforce becomes a hook, with a line here saying so.
- Only I change this file: propose a change in chat, with the line it would replace. At the end of each month I measure it with the kit's instruction-file check, delete what no session needed, and copy it over Codex CLI's global `AGENTS.md`.
