// Regenerates every generated file, in order (chapter 7): the API contract from the Python models,
// then the TypeScript types from the contract. Run it after changing a request or response model,
// then run node check.mjs and fix whatever the type-check reports.
//
// Usage: node tools/regenerate.mjs
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PYTHON = join(ROOT, "python", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
if (!existsSync(PYTHON)) {
  console.error("Not set up yet (missing python/.venv). Run node setup.mjs first.");
  process.exit(1);
}

const steps = [
  ["The API contract", PYTHON, ["-m", "helpdesk.contract", "write", "../contracts/openapi.json"], { cwd: join(ROOT, "python") }],
  // npm is a .cmd script on Windows, which Node only runs through a shell. The command is fixed text.
  ["The TypeScript types", "npm run api-types", [], { cwd: join(ROOT, "ts"), shell: true }],
];
for (const [label, command, args, options] of steps) {
  const run = spawnSync(command, args, { stdio: "inherit", ...options });
  if (run.status !== 0) {
    console.error(`${label}: regenerating failed. Read the output above for the cause.`);
    process.exit(1);
  }
}
console.log("\nRegenerated. Review the changes with git diff, then run node check.mjs.");
