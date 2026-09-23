// The TypeScript package's import rules (chapter 16), checked by npm run deps. dependency-cruiser
// resolves every import to the file it loads, so a rule holds however the import is spelled, and it
// sees dynamic import(), type-only imports and process.getBuiltinModule() too. Each rule's comment
// is printed when the rule is broken, so it says how to fix what broke.
/** @type {import("dependency-cruiser").IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "client-does-not-import-cli",
      severity: "error",
      comment:
        "src/client.ts is a library and src/cli.ts is one program that uses it, so the client must not import the CLI. Move what both need into client.ts or types.ts.",
      from: { path: "^src/client[.]ts$" },
      to: { path: "^src/cli[.]ts$" },
    },
    {
      name: "types-import-nothing-above-them",
      severity: "error",
      comment:
        "src/types.ts and src/api-types.ts describe the API's shapes, so they must not import the client or the CLI. Move the code that needs them into client.ts.",
      from: { path: "^src/(types|api-types)[.]ts$" },
      to: { path: "^src/(client|cli)[.]ts$" },
    },
    {
      name: "only-types-imports-the-generated-file",
      severity: "error",
      comment:
        "src/api-types.ts is generated from the API contract. Only src/types.ts imports it, so a renamed schema changes one file: import the short name from ./types.ts, adding it there if it's missing.",
      from: { pathNot: "^src/types[.]ts$" },
      to: { path: "^src/api-types[.]ts$" },
    },
    {
      name: "only-the-cli-uses-node-builtins",
      severity: "error",
      comment:
        "Only src/cli.ts may use Node's built-in modules, because the client and its types must also run in a browser. Take what you need as an argument, like the client's fetchImpl, and have cli.ts pass it in.",
      from: { path: "^src/", pathNot: "^src/cli[.]ts$" },
      to: { dependencyTypes: ["core"] },
    },
    {
      name: "src-does-not-import-scripts-or-tests",
      severity: "error",
      comment: "src/ is the package; scripts/ and test/ are tools around it. Move the code src/ needs into src/.",
      from: { path: "^src/" },
      to: { path: "^(scripts|test)/" },
    },
    {
      name: "no-circular",
      severity: "error",
      comment:
        "These files import each other in a circle, so none of them can be understood, tested or loaded without the others. Move what they share into a file that imports neither.",
      from: {},
      to: { circular: true },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    // Count imports that exist only for types: the layers hold at compile time too.
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.json" },
    detectProcessBuiltinModuleCalls: true,
  },
};
