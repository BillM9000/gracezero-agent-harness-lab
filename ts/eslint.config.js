// ESLint's part of the TypeScript package's import rules (chapter 16). no-restricted-imports reads
// one file at a time and matches the text of each static import, so it is fast enough to run on
// every edit. It can't see a dynamic import() or process.getBuiltinModule(), and it doesn't resolve
// paths, so the rules between this package's own files, and the gate for this one, are in
// .dependency-cruiser.cjs.
import { builtinModules } from "node:module";

import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

import cliOutputThroughWrite from "./scripts/eslint-rules/cli-output-through-write.ts";

// Every name Node's built-in modules answer to, with and without the node: prefix, taken from Node
// itself instead of typed out. A few, such as node:test, exist only with the prefix.
const BARE = builtinModules.filter((name) => !name.startsWith("node:"));
const NODE_BUILTINS = [...BARE, ...builtinModules.map((name) => (name.startsWith("node:") ? name : `node:${name}`))];

const ONLY_THE_CLI =
  "Only src/cli.ts may use Node's built-in modules, because the client and its types must also run in a browser. Take what you need as an argument, like the client's fetchImpl, and have cli.ts pass it in.";

export default defineConfig([
  {
    files: ["**/*.ts"],
    languageOptions: { parser: tseslint.parser },
    // The lab's own rules (chapter 17), as a plugin defined right here rather than published.
    plugins: { local: { rules: { "cli-output-through-write": cliOutputThroughWrite } } },
    rules: { "local/cli-output-through-write": "error" },
  },
  {
    // Every file in src/ except the command-line tool, including files written later.
    files: ["src/**/*.ts"],
    ignores: ["src/cli.ts"],
    rules: {
      "no-restricted-imports": ["error", { paths: NODE_BUILTINS.map((name) => ({ name, message: ONLY_THE_CLI })) }],
    },
  },
]);
