// Whether a proof names a test the runners collect (chapter 10): shared by tools/progress.mjs, for
// the work list's done items, and tools/features-lock.mjs, for every feature of a locked spec.
//
// A proof is "<test file>::<test name>", from the repository's root. A Python test is a function
// named test* defined at the top of a test_*.py file, under pytest's testpaths when
// python/pyproject.toml sets them; a JavaScript or TypeScript test is a test(...) or it(...) call
// with that title in a *.test.* or *.spec.* file, found in the code rather than in a comment or a
// string. The scan for a test is a simple one (strings, comments and JavaScript's regular
// expressions skipped by their quotes and slashes), not a parser, so a proof it accepts is still
// worth reading.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Where pytest looks for tests, from python/pyproject.toml's [tool.pytest.ini_options] testpaths,
// as folders from the root; none when the file or the setting isn't there.
function pytestPaths(root) {
  const path = join(root, "python", "pyproject.toml");
  if (!existsSync(path)) return [];
  const section = /^\[tool\.pytest\.ini_options\]\s*$([\s\S]*?)(?=^\[|(?![\s\S]))/m.exec(readFileSync(path, "utf8"));
  const paths = section && /^testpaths\s*=\s*\[([^\]]*)\]/m.exec(section[1]);
  return paths ? [...paths[1].matchAll(/["']([^"']+)["']/g)].map((m) => `python/${m[1].replace(/\/+$/, "")}/`) : [];
}

// The source with every string and comment blanked out (newlines kept, so lines and columns stay
// where they were), and the strings themselves with where they start. JavaScript's regular
// expression literals are blanked too, where a slash follows something that can't end a value.
export function scan(text, python) {
  const code = [...text];
  const strings = [];
  const blank = (from, to) => {
    for (let k = from; k < to; k++) if (code[k] !== "\n") code[k] = " ";
  };
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (python ? c === "#" : text.startsWith("//", i)) {
      const end = text.indexOf("\n", i);
      blank(i, end < 0 ? text.length : end);
      i = end < 0 ? text.length : end;
    } else if (!python && text.startsWith("/*", i)) {
      const end = text.indexOf("*/", i + 2);
      blank(i, end < 0 ? text.length : end + 2);
      i = end < 0 ? text.length : end + 2;
    } else if (c === '"' || c === "'" || (!python && c === "`")) {
      const quote = python && text.startsWith(c.repeat(3), i) ? c.repeat(3) : c;
      let j = i + quote.length;
      let value = "";
      while (j < text.length && !text.startsWith(quote, j)) {
        if (text[j] === "\\") {
          value += text[j + 1] ?? "";
          j += 2;
        } else {
          value += text[j];
          j += 1;
        }
      }
      strings.push({ start: i, value });
      const end = Math.min(text.length, j + quote.length);
      blank(i, end);
      i = end;
    } else if (!python && c === "/" && /(^|[(,=:[!&|?{};+\-*%<>~^]|\breturn|\btypeof)\s*$/.test(text.slice(Math.max(0, i - 12), i))) {
      let j = i + 1;
      let inClass = false;
      while (j < text.length && text[j] !== "\n" && (inClass || text[j] !== "/")) {
        if (text[j] === "\\") j += 1;
        else if (text[j] === "[") inClass = true;
        else if (text[j] === "]") inClass = false;
        j += 1;
      }
      blank(i, j + 1);
      i = j + 1;
    } else {
      i += 1;
    }
  }
  return { code: code.join(""), strings };
}

const PYTHON_TEST_FILE = /(^|\/)test_[^/]*\.py$/;
const SCRIPT_TEST_FILE = /\.(test|spec)\.[cm]?[jt]s$/;

// What's wrong with the proof, or null when it names a test the runners collect. `tracked` is the
// set of files git tracks in the repository at `root`, as paths from the root with forward slashes.
export function proofProblem(proof, root, tracked) {
  const match = /^([^:]+)::(.+)$/.exec(proof);
  if (!match) return `"${proof}" isn't a proof. Write it as <test file>::<test name>.`;
  const [, file, name] = match;
  if (!tracked.has(file)) return `its proof file, ${file}, isn't in the repository.`;
  const text = readFileSync(join(root, file), "utf8");
  if (file.endsWith(".py")) {
    const under = pytestPaths(root);
    if (!PYTHON_TEST_FILE.test(file) || (under.length && !under.some((folder) => file.startsWith(folder)))) {
      const where = under.length ? ` under ${under.join(" or ")}` : "";
      return `its proof file, ${file}, isn't a file pytest collects: name a test_*.py file${where}.`;
    }
    if (!/^test\w*$/.test(name)) return `its proof names ${name}, and pytest runs only functions whose names start with test.`;
    const { code } = scan(text, true);
    const found = new RegExp(`^(async\\s+)?def ${escape(name)}\\(`, "m").test(code);
    return found ? null : `its proof names ${name}, which isn't a test in ${file}.`;
  }
  if (!SCRIPT_TEST_FILE.test(file)) {
    return `its proof file, ${file}, isn't a test file: name a *.test.* or *.spec.* file the test runner reads.`;
  }
  const { code, strings } = scan(text, false);
  const found = strings.some((s) => s.value === name && /\b(test|it)\s*\(\s*$/.test(code.slice(Math.max(0, s.start - 40), s.start)));
  return found ? null : `its proof names ${name}, which isn't a test in ${file}.`;
}
