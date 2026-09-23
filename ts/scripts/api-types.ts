// Writes src/api-types.ts from the helpdesk's contract, ../contracts/openapi.json (chapter 7).
// With --check, writes nothing and fails if src/api-types.ts no longer matches the contract.
//
// Usage, from ts/:  npm run api-types            (or: npm run api-types -- --check)
import { existsSync, readFileSync, writeFileSync } from "node:fs";

import { generate, type OpenApiDocument } from "./openapi-to-ts.ts";

const CONTRACT = new URL("../../contracts/openapi.json", import.meta.url);
const OUTPUT = new URL("../src/api-types.ts", import.meta.url);

const doc = JSON.parse(readFileSync(CONTRACT, "utf8")) as OpenApiDocument;
const expected = generate(doc);

if (!process.argv.includes("--check")) {
  writeFileSync(OUTPUT, expected);
  console.log("Wrote src/api-types.ts from ../contracts/openapi.json.");
  process.exit(0);
}

// Each declaration in a generated file, by name, so a mismatch can say which types changed.
function declarations(text: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const block of text.split(/\n(?=(?:\/\*\*.*\*\/\n)?export )/)) {
    const name = /export (?:interface|type) (\w+)/.exec(block)?.[1];
    if (name !== undefined) found.set(name, block.trim());
  }
  return found;
}

const actual = existsSync(OUTPUT) ? readFileSync(OUTPUT, "utf8").replaceAll("\r\n", "\n") : null;
if (actual === expected) {
  console.log("src/api-types.ts matches ../contracts/openapi.json.");
  process.exit(0);
}
if (actual === null) {
  console.error("src/api-types.ts doesn't exist. Create it with: npm run api-types");
  process.exit(1);
}
const before = declarations(actual);
const after = declarations(expected);
const changes = [
  ...[...after.keys()].filter((name) => !before.has(name)).map((name) => `type added: ${name}`),
  ...[...before.keys()].filter((name) => !after.has(name)).map((name) => `type removed: ${name}`),
  ...[...after.keys()].filter((name) => before.has(name) && before.get(name) !== after.get(name)).map((name) => `type changed: ${name}`),
];
console.error("src/api-types.ts no longer matches ../contracts/openapi.json:");
for (const change of changes.length > 0 ? changes : ["only the file's layout differs"]) console.error(`  ${change}`);
console.error("Run npm run api-types, then fix whatever the type-check reports. Never edit src/api-types.ts by hand.");
process.exit(1);
