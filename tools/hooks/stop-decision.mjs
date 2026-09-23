// The decisions behind the Stop hook (tools/hooks/stop-check.mjs, chapter 25), kept apart from
// running anything so the tests can walk a whole session through them.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { failureReport, RERUN, RULES } from "../feedback.mjs";

// How many times in a row the hook may send the agent back. Claude Code has its own limit, 8
// consecutive blocks; this one is lower because each round costs a turn. Three is a starting
// guess: count how often a fix arrives in the third round before changing it.
export const MAX_BLOCKS = 3;

// passed and output come from the fast checks; blocksSoFar is how many times in a row this hook
// has already sent the agent back. Exit 2 is the only exit code that makes the agent go on:
// Claude Code treats any other failing code as a broken hook and lets the agent stop.
export function decide({ passed, output, blocksSoFar }) {
  if (passed) return { exitCode: 0, blocks: 0 };
  if (blocksSoFar >= MAX_BLOCKS) {
    const systemMessage =
      `The fast checks still fail after ${MAX_BLOCKS} rounds of fixes, so the agent was allowed to stop. ` +
      `Run ${RERUN} to see what's left.`;
    return { exitCode: 0, blocks: 0, stdout: JSON.stringify({ systemMessage }) };
  }
  const blocks = blocksSoFar + 1;
  const stderr = [
    `The fast checks failed, so the work isn't finished (round ${blocks} of ${MAX_BLOCKS}).`,
    "",
    failureReport(output),
    "",
    `Run them again with: ${RERUN}`,
    ...RULES,
  ].join("\n");
  return { exitCode: 2, blocks, stderr };
}

// Each stop runs the hook afresh, so the count lives in a file per session. The session id comes
// from the hook's input: only safe characters are kept, so it can't choose where the file goes.
export function stateFile(sessionId, dir = process.env.LAB_HOOK_STATE_DIR ?? join(tmpdir(), "agent-harness-lab-hooks")) {
  const name = String(sessionId || "unknown").replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 100);
  return join(dir, `stop-${name}.json`);
}

export function readBlocks(file) {
  try {
    const blocks = JSON.parse(readFileSync(file, "utf8")).blocks;
    return Number.isInteger(blocks) && blocks >= 0 ? blocks : 0;
  } catch {
    return 0;
  }
}

export function saveBlocks(file, blocks) {
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify({ blocks }));
}

// The repository the agent is working in: the nearest folder at or above its working directory
// that holds a check.mjs, which is right in a subfolder or a worktree. Otherwise this lab's root.
export function repositoryRoot(cwd) {
  let dir = resolve(cwd);
  for (;;) {
    if (existsSync(join(dir, "check.mjs"))) return dir;
    const up = dirname(dir);
    if (up === dir) return resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
    dir = up;
  }
}
