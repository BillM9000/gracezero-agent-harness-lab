// Runs git for a test or script that builds a repository of its own (the script tests from chapter 4
// on, and chapter 31's demo history), so the repository comes out the same on every
// machine and a failure says why.
//
// - The machine's own git setup stays out. No system or global configuration (GIT_CONFIG_NOSYSTEM,
//   and GIT_CONFIG_GLOBAL=/dev/null, which Git for Windows also reads as empty), no GIT_ variable
//   from the caller (a git hook's environment carries GIT_DIR and GIT_INDEX_FILE), no
//   XDG_CONFIG_HOME, HOME in the folder git runs in, and a fixed name, email and default branch,
//   with signing off. A call's own -c settings come after these, so a test can still name its author.
// - A failure throws with git's exit code, stdout and stderr. `commit -q` with nothing staged exits
//   1 and says why on stdout only, so stderr alone can be empty.
// - On Windows, git's rename of a file it has just written (a loose object, the new index) can fail
//   with "Permission denied" while another program, such as a virus scanner, has the file open.
//   Such a call is run again, up to 5 more times over about 3 seconds; git writes nothing half-done
//   when it reports that error. So is a git that Windows couldn't start (exit 0xC0000142, seen with
//   many processes starting at once), which did nothing. Each retry is reported on stderr.
import { spawnSync } from "node:child_process";

const SETTINGS = ["user.name=Lab Test", "user.email=lab-test@example.com", "init.defaultBranch=main", "commit.gpgsign=false", "tag.gpgsign=false"];
const DELAYS_MS = [100, 200, 400, 800, 1600];

// The environment every call gets: the caller's, without its GIT_ variables, plus `extra`.
function gitEnv(cwd, extra = {}) {
  const env = {};
  for (const [name, value] of Object.entries(process.env)) {
    if (!/^GIT_/i.test(name) && !/^XDG_CONFIG_HOME$/i.test(name)) env[name] = value;
  }
  return { ...env, GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null", HOME: cwd, GIT_TERMINAL_PROMPT: "0", ...extra };
}

const NOT_STARTED = 0xc0000142; // STATUS_DLL_INIT_FAILED: Windows couldn't start the process.

// A failure worth another try: git was refused a file it had just written, or never started; not a
// mistake in the call. Not a lock another git holds (two gits in one repository is a bug in the
// test), and not "repository has been updated, but unable to write new index file": that commit landed.
export function isTransient(status, stderr) {
  if (status === NOT_STARTED) return true;
  return status === 128 && /Permission denied|unable to write new index file/.test(stderr);
}

const pause = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

// Runs `git ...args` in `cwd` and returns its stdout; throws with everything git printed if it fails.
export function git(cwd, args, { env = {} } = {}) {
  const attempts = [];
  for (let attempt = 0; ; attempt++) {
    const run = spawnSync("git", [...SETTINGS.flatMap((s) => ["-c", s]), ...args], { cwd, encoding: "utf8", env: gitEnv(cwd, env) });
    if (run.status === 0) return run.stdout;
    attempts.push(`exit ${run.status ?? run.signal ?? run.error?.message}\n--- stdout ---\n${run.stdout ?? ""}--- stderr ---\n${run.stderr ?? ""}`);
    if (attempt >= DELAYS_MS.length || !isTransient(run.status, run.stderr ?? "")) break;
    const command = args.find((arg, i) => !arg.startsWith("-") && args[i - 1] !== "-c");
    process.stderr.write(`git-run: git ${command} in ${cwd} failed (${run.stderr.trim().split("\n")[0] || `exit ${run.status}`}); trying again\n`);
    pause(DELAYS_MS[attempt]);
  }
  const tries = attempts.length > 1 ? ` (${attempts.length} tries)` : "";
  throw new Error(`git ${args.join(" ")} failed in ${cwd}${tries}:\n${attempts.join("\n")}`);
}
