// What the fix loop (tools/fix-loop.mjs, chapter 25) treats as the checks themselves: a change to
// any of these files stops the loop for a person, because weakening a check, or the data it judges
// against, is often the quickest way to make it pass.
//
// Three parts:
//   - ALWAYS: the check runner, the scripts, the agent's settings and CI, whatever check reads them.
//   - CHECK_FILES: for every check `node check.mjs --list` prints, the code and data that decide
//     whether it passes: its module, its rules, its golden sets and the records it compares with.
//     tools/protected.test.mjs fails when a check has no entry, when an entry matches no file, or
//     when a module or script check.mjs runs isn't covered, so a new check can't slip past the loop.
//   - CONFIG_NAMES: a tool's configuration file wherever it appears, tracked or new. Ruff, for one,
//     prefers a ruff.toml beside pyproject.toml, so a new python/ruff.toml with ignore = ["F401"]
//     turns a failing lint into a pass without touching the file that held the rule.
//
// The data the app serves (help articles, seed data, agent definitions) isn't here: changing it can
// be a fix, and the gate's fingerprint (chapter 23) catches a change to what the model is given.

const TOOLS = /^tools\//;

export const ALWAYS = [/^check\.mjs$/, TOOLS, /^\.claude\//, /^\.github\//, /^setup\.mjs$/];

export const CHECK_FILES = {
  "Python lint (ruff check)": [/^python\/pyproject\.toml$/],
  "Python format (ruff format --check)": [/^python\/pyproject\.toml$/],
  "Python import rules (lint-imports)": [/^python\/pyproject\.toml$/],
  "Python model-text rule (python -m helpdesk_lint)": [/^python\/src\/helpdesk_lint\//],
  "Agent definitions (python -m agent_policy)": [/^python\/src\/agent_policy\//, /^python\/agents\/(policy|models)\.toml$/],
  "MCP server catalog (python -m mcp_governance)": [/^python\/src\/mcp_governance\//, /^python\/catalog\//],
  "Knowledge-base retrieval (python -m helpdesk.kb eval)": [/^python\/src\/helpdesk\/kb\.py$/, /^python\/evals\/kb_questions\.json$/],
  "Golden sets (python -m helpdesk.evals check)": [
    /^python\/src\/helpdesk\/evals\.py$/,
    /^python\/src\/helpdesk\/assistant\/grading\.py$/,
    /^python\/evals\/(tasks|reasons|injections)\.json$/,
  ],
  "Model judges (python -m helpdesk.judge check)": [
    /^python\/src\/helpdesk\/judge\.py$/,
    /^python\/src\/helpdesk\/assistant\/judging\.py$/,
    /^python\/evals\/(judged|judge-mock)\.json$/,
    /^python\/evals\/rubrics\//,
  ],
  "Promotion gate (python -m helpdesk.gate check)": [
    /^python\/src\/helpdesk\/gate\.py$/,
    /^python\/src\/helpdesk\/assistant\/gating\.py$/,
    /^python\/evals\/(gate|promoted)\.json$/,
  ],
  "Model gateway (python -m helpdesk.gateway check)": [
    /^python\/src\/helpdesk\/gateway\.py$/,
    /^python\/gateway\//,
    /^python\/agents\/(policy|models)\.toml$/,
  ],
  "Use-case readiness (python -m helpdesk.readiness check)": [
    /^python\/src\/helpdesk\/readiness\.py$/,
    /^python\/src\/readiness\//,
    /^python\/usecases\//,
  ],
  "Golden path (python -m helpdesk.golden_path check)": [
    /^python\/src\/helpdesk\/golden_path\.py$/,
    /^python\/src\/golden_path\//,
    /^python\/golden-path\//,
  ],
  "Spec review (python -m helpdesk.spec_review check)": [/^python\/src\/helpdesk\/spec_review\.py$/, /^python\/spec-review\//],
  "API contract (python -m helpdesk.contract)": [/^python\/src\/helpdesk\/contract\.py$/],
  "Python tests (pytest)": [/^python\/tests\//, /^python\/pyproject\.toml$/],
  "TypeScript API types (npm run api-types)": [/^ts\/scripts\//, /^ts\/package\.json$/],
  "TypeScript type-check": [/^ts\/tsconfig\.json$/, /^ts\/package\.json$/],
  "TypeScript import rules (eslint)": [/^ts\/eslint\.config\.js$/, /^ts\/scripts\/eslint-rules\//],
  "TypeScript dependency rules (dependency-cruiser)": [/^ts\/\.dependency-cruiser\.cjs$/],
  "TypeScript tests": [/^ts\/test\//, /^ts\/package\.json$/],
  "Script tests": [TOOLS, /^postings\/[^/]+\.test\.mjs$/, /^postings\/sample-[^/]+\.json$/, /^templates\//],
  "Setup's path limit (tools/install-paths.mjs)": [TOOLS, /^setup\.mjs$/],
  "Lock files (tools/lockfiles.mjs)": [TOOLS, /^python\/requirements-lock\.txt$/, /^ts\/package-lock\.json$/],
  "Instruction files (tools/instruction-files.mjs)": [TOOLS],
  "Documentation claims (tools/doc-claims.mjs)": [TOOLS],
  "Work list (tools/progress.mjs)": [TOOLS],
};

// A tool's configuration, by the file's name, in any folder: the linters, formatters, type checkers
// and test runners the checks use or would pick up, and git's own ignore and attribute files, which
// decide what the loop can see (an ignored file isn't listed; a file marked -diff shows no lines).
export const CONFIG_NAMES = new RegExp(
  "(^|/)(" +
    [
      String.raw`\.?ruff\.toml`,
      String.raw`pyproject\.toml`,
      String.raw`setup\.cfg`,
      String.raw`tox\.ini`,
      String.raw`pytest\.ini`,
      String.raw`conftest\.py`,
      String.raw`\.importlinter`,
      String.raw`\.flake8`,
      String.raw`mypy\.ini`,
      String.raw`\.coveragerc`,
      String.raw`pyrightconfig\.json`,
      String.raw`package\.json`,
      String.raw`[jt]sconfig(\.[\w-]+)*\.json`,
      String.raw`eslint\.config\.[cm]?[jt]s`,
      String.raw`\.eslintrc(\.\w+)?`,
      String.raw`\.eslintignore`,
      String.raw`\.dependency-cruiser(\.[\w-]+)*\.[cm]?js(on)?`,
      String.raw`vite(st)?\.config\.[cm]?[jt]s`,
      String.raw`\.gitignore`,
      String.raw`\.gitattributes`,
    ].join("|") +
    ")$",
);

export const PROTECTED = [...ALWAYS, ...new Set(Object.values(CHECK_FILES).flat()), CONFIG_NAMES];

// Paths as git prints them: forward slashes, relative to the repository's root.
export const isProtected = (file, patterns = PROTECTED) => patterns.some((p) => p.test(file));
