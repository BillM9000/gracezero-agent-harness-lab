// The lab's custom ESLint rule (chapter 17), tested with ESLint's RuleTester: code it must pass,
// code it must report, the message it reports, and exactly what its fix and its suggestion
// turn the code into.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint, RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, expect, it } from "vitest";

import rule from "../scripts/eslint-rules/cli-output-through-write.ts";

RuleTester.describe = describe;
RuleTester.it = it;

const ROOT = fileURLToPath(new URL("..", import.meta.url));

describe("the rule in the lab's ESLint configuration", () => {
  it("fixes a console.log planted in the CLI's run() back to write()", async () => {
    const cli = readFileSync(join(ROOT, "src", "cli.ts"), "utf8");
    const planted = cli.replace("write(USAGE);", "console.log(USAGE);");
    expect(planted).not.toBe(cli);
    const eslint = new ESLint({ cwd: ROOT, fix: true });
    const [result] = await eslint.lintText(planted, { filePath: join(ROOT, "src", "cli.ts") });
    expect(result?.output).toBe(cli);
  });
});

const ruleTester = new RuleTester({ languageOptions: { parser: tseslint.parser } });
const RUN = "function run(write: (line: string) => void)";

ruleTester.run("cli-output-through-write", rule, {
  valid: [
    `${RUN} { write("done"); }`,
    // No write parameter anywhere around it: the console is the way out, as in cli.ts's main block.
    "const main = (line: string) => console.log(line);",
    // A local variable called write isn't the parameter the rule is about.
    "function f() { const write = (line: string) => line; console.log(write('x')); }",
  ],
  invalid: [
    {
      code: `${RUN} { console.log("done"); }`,
      output: `${RUN} { write("done"); }`,
      errors: [
        {
          message:
            "Use write(...) instead of console.log(...). This function takes write so that tests can read its output; console.log goes straight to the terminal, where no test sees it.",
        },
      ],
    },
    {
      // Inside a callback, write still resolves to run's parameter.
      code: "function run(items: string[], write: (line: string) => void) { items.forEach((item) => console.log(item)); }",
      output: "function run(items: string[], write: (line: string) => void) { items.forEach((item) => write(item)); }",
      errors: [{ messageId: "useWrite", data: { method: "log" } }],
    },
    {
      // console.error is reported with a suggestion an editor offers, never fixed on its own.
      code: `${RUN} { console.error("failed"); }`,
      output: null,
      errors: [
        {
          messageId: "useWrite",
          data: { method: "error" },
          suggestions: [{ messageId: "replaceWithWrite", data: { method: "error" }, output: `${RUN} { write("failed"); }` }],
        },
      ],
    },
    {
      // Two arguments: write takes one line, so nothing can be rewritten safely. Report only.
      code: `${RUN} { console.log("a", "b"); }`,
      output: null,
      errors: [{ messageId: "useWrite", data: { method: "log" }, suggestions: [] }],
    },
  ],
});
