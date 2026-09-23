// The TypeScript package's import rules (chapter 16) catch what they claim to, and they read every
// file. dependency-cruiser runs on a copy of the package with one violation planted in it, so the
// real source is never touched; the real package, which breaks no rule, is the control. ESLint
// lints a line of code as if it were in a given file, so it needs no copy.
import { spawnSync } from "node:child_process";
import { appendFileSync, cpSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import { afterEach, describe, expect, it } from "vitest";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const DEPCRUISE = join(ROOT, "node_modules", "dependency-cruiser", "bin", "dependency-cruiser.mjs");
const FOLDERS = ["src", "scripts", "test"];

// Every TypeScript file in the package, read from the disk rather than listed by hand.
function typeScriptFiles(): string[] {
  return FOLDERS.flatMap((folder) =>
    readdirSync(join(ROOT, folder), { recursive: true, encoding: "utf8" })
      .filter((name) => name.endsWith(".ts"))
      .map((name) => `${folder}/${name.replaceAll("\\", "/")}`),
  ).sort();
}

function depcruise(cwd: string, outputType: "json" | "err-long"): { code: number | null; output: string } {
  const result = spawnSync(
    process.execPath,
    [DEPCRUISE, ...FOLDERS, "--config", ".dependency-cruiser.cjs", "--output-type", outputType],
    { cwd, encoding: "utf8" },
  );
  const output = result.stdout + result.stderr;
  // err-long wraps long lines; collapse whitespace so assertions can match whole sentences.
  return { code: result.status, output: outputType === "json" ? output : output.replace(/\s+/g, " ") };
}

describe("dependency-cruiser", () => {
  const copies: string[] = [];
  afterEach(() => {
    for (const dir of copies.splice(0)) rmSync(dir, { recursive: true, force: true });
  });

  // A copy of the package's sources and configuration, with `line` added to the end of `file`.
  function plant(file: string, line: string): string {
    const dir = mkdtempSync(join(tmpdir(), "boundaries-"));
    copies.push(dir);
    for (const name of [...FOLDERS, "tsconfig.json", ".dependency-cruiser.cjs"]) {
      cpSync(join(ROOT, name), join(dir, name), { recursive: true });
    }
    appendFileSync(join(dir, file), `\n${line}\n`);
    return dir;
  }

  it("reads every TypeScript file in the package", () => {
    // A cruise that could not parse TypeScript would read no files and still report no violations.
    const { code, output } = depcruise(ROOT, "json");
    expect(code, output).toBe(0);
    const modules = (JSON.parse(output) as { modules: { source: string }[] }).modules;
    const read = modules.map((m) => m.source).filter((source) => source.endsWith(".ts") && !source.startsWith("node_modules"));
    expect(read.sort()).toEqual(typeScriptFiles());
  });

  it("finds no violation in the real package", () => {
    const { code, output } = depcruise(ROOT, "err-long");
    expect(code, output).toBe(0);
    expect(output).toContain("no dependency violations found");
  });

  it("catches the client importing the CLI, and says how to fix it", () => {
    const { code, output } = depcruise(plant("src/client.ts", 'export { run } from "./cli.ts";'), "err-long");
    expect(code).not.toBe(0);
    expect(output).toContain("client-does-not-import-cli: src/client.ts → src/cli.ts");
    expect(output).toContain("Move what both need into client.ts or types.ts.");
  });

  it("catches the same import written as a dynamic import()", () => {
    const dir = plant("src/client.ts", 'export const later = () => import("./cli.ts");');
    const { code, output } = depcruise(dir, "err-long");
    expect(code).not.toBe(0);
    expect(output).toContain("client-does-not-import-cli: src/client.ts → src/cli.ts");
  });

  it("catches an import that exists only for types", () => {
    const dir = plant("src/types.ts", 'export type { HelpdeskClient } from "./client.ts";');
    const { code, output } = depcruise(dir, "err-long");
    expect(code).not.toBe(0);
    expect(output).toContain("types-import-nothing-above-them: src/types.ts → src/client.ts");
  });

  it("catches the CLI importing the generated file directly", () => {
    const dir = plant("src/cli.ts", 'export type { Ticket as RawTicket } from "./api-types.ts";');
    const { code, output } = depcruise(dir, "err-long");
    expect(code).not.toBe(0);
    expect(output).toContain("only-types-imports-the-generated-file: src/cli.ts → src/api-types.ts");
    expect(output).toContain("import the short name from ./types.ts");
  });

  it("catches a Node built-in in the client, however it is loaded", () => {
    for (const line of [
      'export { readFileSync } from "node:fs";',
      'export const later = () => import("node:fs");',
      'export const fs = process.getBuiltinModule("node:fs");',
    ]) {
      const { code, output } = depcruise(plant("src/client.ts", line), "err-long");
      expect(code, line).not.toBe(0);
      expect(output, line).toContain("only-the-cli-uses-node-builtins: src/client.ts → fs");
    }
  });

  it("catches the package importing a script", () => {
    const dir = plant("src/client.ts", 'export { typeFor } from "../scripts/openapi-to-ts.ts";');
    const { code, output } = depcruise(dir, "err-long");
    expect(code).not.toBe(0);
    expect(output).toContain("src-does-not-import-scripts-or-tests: src/client.ts → scripts/openapi-to-ts.ts");
  });

  it("catches files that import each other in a circle", () => {
    const dir = plant("scripts/openapi-to-ts.ts", 'import "./api-types.ts";');
    const { code, output } = depcruise(dir, "err-long");
    expect(code).not.toBe(0);
    expect(output).toContain("no-circular:");
    expect(output).toContain("scripts/openapi-to-ts.ts → scripts/api-types.ts");
  });
});

describe("ESLint", () => {
  const eslint = new ESLint({ cwd: ROOT });

  async function problems(code: string, filePath: string): Promise<string[]> {
    const [result] = await eslint.lintText(code, { filePath: join(ROOT, filePath) });
    return (result?.messages ?? []).map((m) => `${m.ruleId}: ${m.message}`);
  }

  it("lints every TypeScript file in the package", async () => {
    // A file that no configuration matches is skipped without a word, so check that none was.
    const results = await eslint.lintFiles(["."]);
    const linted = results.map((r) => relative(ROOT, r.filePath).replaceAll("\\", "/")).filter((f) => f.endsWith(".ts"));
    expect(linted.sort()).toEqual(typeScriptFiles());
    expect(results.flatMap((r) => r.messages)).toEqual([]);
  });

  it("stops the client importing a Node built-in, under either name, and says how to fix it", async () => {
    for (const name of ["node:fs", "fs", "node:fs/promises", "fs/promises"]) {
      const found = await problems(`import { readFile } from "${name}";\n`, "src/client.ts");
      expect(found, name).toHaveLength(1);
      expect(found[0], name).toContain("Only src/cli.ts may use Node's built-in modules");
      expect(found[0], name).toContain("have cli.ts pass it in");
    }
  });

  it("lets the CLI import them", async () => {
    expect(await problems('import { readFile } from "node:fs";\n', "src/cli.ts")).toEqual([]);
  });

  it("covers a file in src/ that doesn't exist yet", async () => {
    expect(await problems('import { readFile } from "node:fs";\n', "src/cache.ts")).toHaveLength(1);
  });

  it("does not see a dynamic import: dependency-cruiser's rule is the one that does", async () => {
    // A known limit, kept as a test so the day ESLint starts catching it, this test says so.
    expect(await problems('export const later = () => import("node:fs");\n', "src/client.ts")).toEqual([]);
  });
});
