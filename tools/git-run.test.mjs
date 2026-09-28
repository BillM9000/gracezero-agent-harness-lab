// Tests for tools/git-run.mjs: a repository a test builds ignores the machine's git setup and the
// caller's GIT_ variables, a failure carries everything git printed, and only a refused file is tried
// again.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { git, isTransient } from "./git-run.mjs";

const made = [];
after(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});
function temporary(prefix) {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  made.push(dir);
  return dir;
}

test("the caller's git configuration and GIT_ variables don't reach the repository", () => {
  // A global configuration that breaks every commit: a hook that refuses, and signing with a program
  // that doesn't exist. GIT_DIR and GIT_INDEX_FILE point somewhere else, as they do inside a git hook.
  const elsewhere = temporary("git-run-elsewhere-");
  mkdirSync(join(elsewhere, "hooks"));
  writeFileSync(join(elsewhere, "hooks", "pre-commit"), "#!/bin/sh\nexit 1\n", { mode: 0o755 });
  const hooks = join(elsewhere, "hooks").replaceAll("\\", "/");
  writeFileSync(join(elsewhere, "global.gitconfig"), `[core]\n\thooksPath = ${hooks}\n[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = no-such-gpg\n`);
  const planted = {
    GIT_CONFIG_GLOBAL: join(elsewhere, "global.gitconfig"),
    GIT_DIR: join(elsewhere, "not-here.git"),
    GIT_INDEX_FILE: join(elsewhere, "not-here.index"),
  };

  // The planted setup does break a plain git commit, so passing below means it was kept out.
  const control = temporary("git-run-control-");
  const plain = (args) => spawnSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.com", ...args], { cwd: control, encoding: "utf8", env: { ...process.env, GIT_CONFIG_GLOBAL: planted.GIT_CONFIG_GLOBAL } });
  plain(["init", "-q"]);
  writeFileSync(join(control, "a.txt"), "a");
  plain(["add", "a.txt"]);
  assert.notEqual(plain(["commit", "-q", "-m", "one"]).status, 0);

  const root = temporary("git-run-");
  const saved = Object.fromEntries(Object.keys(planted).map((name) => [name, process.env[name]]));
  Object.assign(process.env, planted);
  try {
    git(root, ["init", "-q"]);
    writeFileSync(join(root, "a.txt"), "a");
    git(root, ["add", "a.txt"]);
    git(root, ["commit", "-q", "-m", "one"]);
  } finally {
    for (const [name, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
  assert.ok(existsSync(join(root, ".git", "HEAD")));
  assert.ok(!existsSync(planted.GIT_DIR));
  assert.equal(git(root, ["log", "-1", "--format=%an <%ae> %s"]).trim(), "Lab Test <lab-test@example.com> one");
});

test("a call's own -c settings and environment still apply", () => {
  const root = temporary("git-run-");
  git(root, ["init", "-q"]);
  writeFileSync(join(root, "a.txt"), "a");
  git(root, ["add", "a.txt"]);
  const date = "2026-01-02T12:00:00.000Z";
  git(root, ["-c", "user.name=Copilot", "commit", "-q", "-m", "one"], { env: { GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date } });
  assert.equal(git(root, ["log", "-1", "--format=%an %aI %cI"]).trim(), "Copilot 2026-01-02T12:00:00Z 2026-01-02T12:00:00Z");
});

test("a failed call throws with git's exit code, stdout and stderr", () => {
  const root = temporary("git-run-");
  git(root, ["init", "-q"]);
  // Nothing staged: commit -q exits 1 and explains only on stdout.
  assert.throws(
    () => git(root, ["commit", "-q", "-m", "empty"]),
    (error) => {
      assert.match(error.message, /^git commit -q -m empty failed in /);
      assert.match(error.message, /exit 1\n--- stdout ---\n[^]*nothing to commit[^]*--- stderr ---\n/);
      assert.doesNotMatch(error.message, /tries\)/);
      return true;
    },
  );
});

test("only a file another program held open, or a git that never started, is tried again", () => {
  // What git printed when a file it had just written was held open, seen while the script tests ran.
  for (const stderr of [
    "error: unable to write file .git/objects/84/94ac27064713465d43ddea83398365ac0ba721: Permission denied\nerror: client/src/form.js: failed to insert into database\nerror: unable to index file 'client/src/form.js'\nfatal: updating files failed\n",
    "error: unable to write file .git/objects/2b/682a65b5f1c056273fd4f86e08d0f9591fd112: Permission denied\nfatal: failed to write commit object\n",
    "fatal: unable to write new index file\n",
  ]) {
    assert.ok(isTransient(128, stderr), stderr);
  }
  // A git that Windows couldn't start (0xC0000142), seen with many processes starting at once.
  assert.ok(isTransient(3221225794, ""));
  // Two gits in one repository, a commit that already landed, and a plain failure are not retried.
  for (const [status, stderr] of [
    [128, "fatal: Unable to create 'C:/t/.git/index.lock': File exists.\n\nAnother git process seems to be running in this repository"],
    [128, "fatal: repository has been updated, but unable to write\nnew index file. Check that disk is not full and quota is\nnot exceeded, and then \"git restore --staged :/\" to recover.\n"],
    [1, ""],
    [1, "error: open(\"a.txt\"): Permission denied\n"],
  ]) {
    assert.ok(!isTransient(status, stderr), stderr);
  }
});
