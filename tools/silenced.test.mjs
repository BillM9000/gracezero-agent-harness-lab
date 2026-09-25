// Tests for tools/silenced.mjs (chapter 26): which lines switch a rule off, and which lines a diff
// adds.
import assert from "node:assert/strict";
import { test } from "node:test";
import { addedLines, newlyAdded, SILENCED, silenced } from "./silenced.mjs";

const SWITCHED_OFF = [
  "import os  # noqa: F401",
  "value = thing()  # type: ignore[attr-defined]",
  "if debug:  # pragma: no cover",
  "subprocess.run(cmd, shell=True)  # nosec",
  "print(response.text)  # HDK101: the demo prints the raw reply on purpose",
  "@pytest.mark.skip(reason='flaky')",
  "@pytest.mark.xfail",
  "    pytest.skip('needs a network')",
  "// eslint-disable-next-line no-console",
  "/* eslint-disable */",
  "// @ts-ignore",
  "// @ts-expect-error: the types are wrong",
  "it.skip('writes the file', () => {});",
  "test.skip('reads the file', () => {});",
  "describe.skip('the parser', () => {});",
];

const LEFT_ALONE = [
  "import os",
  "# a comment about the type of ignore lists",
  "def skip(self): ...",
  "items.skip(3)",
  "const disabled = true;",
  "notes = 'noqa is a ruff directive'",
];

test("each way of switching a rule off is recognized", () => {
  for (const line of SWITCHED_OFF) assert.match(line, SILENCED, line);
});

test("ordinary lines that mention the words are left alone", () => {
  for (const line of LEFT_ALONE) assert.doesNotMatch(line, SILENCED, line);
});

test("a diff's added lines come with their file, and Markdown is left out", () => {
  const diff = [
    "diff --git a/app.py b/app.py",
    "--- a/app.py",
    "+++ b/app.py",
    "@@ -1,0 +2 @@",
    "+import os  # noqa: F401",
    "-import sys",
    "diff --git a/NOTES.md b/NOTES.md",
    "--- a/NOTES.md",
    "+++ b/NOTES.md",
    "@@ -1,0 +1 @@",
    "+Use # noqa sparingly.",
    "diff --git a/old.py b/old.py",
    "--- a/old.py",
    "+++ /dev/null",
  ].join("\n");
  const added = addedLines(diff);
  assert.deepEqual(added, [{ file: "app.py", text: "import os  # noqa: F401" }]);
  assert.deepEqual(silenced(added), ["app.py: import os  # noqa: F401"]);
});

test("only lines the second list adds count, repeats included", () => {
  assert.deepEqual(newlyAdded(["a: x", "b: y"], ["a: x", "b: y", "a: x"]), ["a: x"]);
  assert.deepEqual(newlyAdded(["a: x"], ["a: x"]), []);
});
