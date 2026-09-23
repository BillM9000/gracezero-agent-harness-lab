// Claude Code's Stop hook (chapter 25), wired up in .claude/settings.json: when the agent says
// it's done, run the fast checks, and if they fail, send the report back so it keeps working.
//
// It reads the hook's JSON input on stdin, or from --input <file> when you try it by hand, and
// ends one of three ways:
//   - the checks pass: exit 0 and print nothing, and the agent stops;
//   - they fail: exit 2 with the report on stderr, which the agent is given as the reason to go on;
//   - they have failed three times in a row: exit 0 so the agent can stop, with a systemMessage
//     that tells the person, because another round is unlikely to help.
// Codex documents the same contract for its Stop hook: stop_hook_active in; exit 2 with the reason
// on stderr to go on; exit 0 with nothing, or with a systemMessage, to stop.
import { readFileSync } from "node:fs";
import { runFastChecks } from "../feedback.mjs";
import { decide, readBlocks, repositoryRoot, saveBlocks, stateFile } from "./stop-decision.mjs";

const at = process.argv.indexOf("--input");
const input = JSON.parse(readFileSync(at > 0 ? process.argv[at + 1] : 0, "utf8"));

// stop_hook_active is true when this stop follows one a Stop hook refused. Otherwise the agent is
// stopping for the first time since the person spoke, and the count starts again.
const file = stateFile(input.session_id);
const blocksSoFar = input.stop_hook_active ? readBlocks(file) : 0;

const { passed, output } = runFastChecks(repositoryRoot(input.cwd ?? process.cwd()));
const result = decide({ passed, output, blocksSoFar });
saveBlocks(file, result.blocks);
if (result.stdout) process.stdout.write(`${result.stdout}\n`);
if (result.stderr) process.stderr.write(`${result.stderr}\n`);
process.exit(result.exitCode);
