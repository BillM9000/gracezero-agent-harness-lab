// A stand-in for a coding agent, for chapter 25's Try it. tools/fix-loop.mjs runs it like any agent
// command, with the prompt on stdin, but no model is involved and nothing is spent. It makes the
// fixes the lab's own tools make safely, ruff's in python/ and ESLint's in ts/, and nothing else,
// so it can fix some failures and not others.
//
// With --cheat it makes the checks pass the careless way instead: it raises the platform's turn
// limit in python/agents/policy.toml, so you can watch the loop refuse a change to the checks.
// With --silence it switches ruff's rule off on each line ruff reports, with ruff's own --add-noqa,
// so you can watch the loop stop an attempt that silences a rule, and count it (chapter 26).
// With --rewrite-docs it takes the code's side of every claimed number the report says is wrong:
// it writes the counted number into the document, so you can watch the loop stop an attempt that
// makes a document agree with code that may be the thing that's wrong (chapter 34).
//
// Run it from the repository root:
//   node tools/stand-in-agent.mjs [--cheat | --silence | --rewrite-docs] < prompt.txt
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const WINDOWS = process.platform === "win32";
const ruff = join(root, "python", ".venv", WINDOWS ? "Scripts/ruff.exe" : "bin/ruff");
const prompt = readFileSync(0, "utf8");
console.log(`stand-in agent: read a prompt of ${prompt.split("\n").length} lines.`);

if (process.argv.includes("--cheat")) {
  const policy = join(root, "python", "agents", "policy.toml");
  writeFileSync(policy, readFileSync(policy, "utf8").replace(/^max_turns = \d+/m, "max_turns = 100"));
  console.log("stand-in agent: raised the policy's turn limit to 100.");
} else if (process.argv.includes("--silence")) {
  spawnSync(ruff, ["check", "--add-noqa", "--quiet", "."], { cwd: join(root, "python"), encoding: "utf8" });
  console.log("stand-in agent: ran ruff check --add-noqa in python/.");
} else if (process.argv.includes("--rewrite-docs")) {
  // tools/doc-claims.mjs reports "- FILE:LINE: says N <what>, but there are M. Update the document, ..."
  for (const m of prompt.matchAll(/^\s*- ([^\s:]+):(\d+): says [\d,]+ .*?, but there are ([\d,]+)\./gm)) {
    const [, file, number, counted] = m;
    const path = join(root, file);
    const lines = readFileSync(path, "utf8").split("\n");
    lines[number - 1] = lines[number - 1].replace(/(<!--\s*claim:\s*[\w-]+\s*-->\s*)\d[\d,]*/, (_, marker) => marker + counted);
    writeFileSync(path, lines.join("\n"));
    console.log(`stand-in agent: made ${file}:${number} say ${counted}, the number the check counted.`);
  }
} else {
  const steps = [
    ["ruff check --fix", ruff, ["check", "--fix", "--quiet", "."], "python"],
    ["ruff format", ruff, ["format", "--quiet", "."], "python"],
    ["eslint --fix", process.execPath, ["node_modules/eslint/bin/eslint.js", "--fix", "--quiet", "."], "ts"],
  ];
  for (const [label, program, args, folder] of steps) {
    spawnSync(program, args, { cwd: join(root, folder), encoding: "utf8" });
    console.log(`stand-in agent: ran ${label} in ${folder}/.`);
  }
}
