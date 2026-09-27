// The guards this repository breaks on purpose, for tools/mutate.mjs (chapter 24). Each entry names
// the guard, the file and the exact text to change, what to change it to, and the test command that
// must then fail. Add entries when a chapter adds a guard. Chapters 9, 16 to 18, 24, 25 and 31 are
// here, the script tests' git runner (tools/git-run.mjs), chapter 7's consumer test and chapter 1's
// tally's check for missing fields; the guards from earlier chapters were broken by hand when they
// were built (CHANGELOG.md records each time) and are the next candidates to add.

const pytest = (...tests) => ({ cwd: "python", python: ["-m", "pytest", "-q", "-p", "no:cacheprovider", ...tests] });
const vitest = (file, name) => ({ cwd: "ts", vitest: [file, "-t", name] });
// One Node test, by the start of its name.
const nodeTest = (file, name) => ({ node: ["--test", "--test-name-pattern", `^${name}`, file] });

const LAYERS = "tests/guardrails/test_layers_contract.py";
const LINT = "tests/test_helpdesk_lint.py";
const POLICY = "tests/test_agent_policy.py";
const fixture = (name) => pytest(`${POLICY}::test_each_fixture_gets_exactly_the_verdict_it_names[${name}]`);
const DC = "ts/.dependency-cruiser.cjs";
const ESLINT = "ts/eslint.config.js";
const RULE = "ts/scripts/eslint-rules/cli-output-through-write.ts";
const MODEL_TEXT = "python/src/helpdesk_lint/model_text.py";
const AGENT_RULES = "python/src/agent_policy/rules.py";
const FEEDBACK_TESTS = "tools/feedback.test.mjs";
const STOP_TESTS = "tools/hooks/stop-check.test.mjs";
const LOOP_TESTS = "tools/fix-loop.test.mjs";
const REWORK = "tools/rework.mjs";
const REWORK_TESTS = "tools/rework.test.mjs";
const RETRIEVAL = "python/src/helpdesk/services/retrieval.py";
const RETRIEVAL_TESTS = "tests/test_retrieval.py";
const KB_CLI = "python/src/helpdesk/kb.py";
const KB_CLI_TESTS = "tests/test_kb_cli.py";
const CITATIONS = "python/src/helpdesk/services/citations.py";
const CITATIONS_TESTS = "tests/test_citations.py";
const PROTECTED_MJS = "tools/protected.mjs";
const PROTECTED_TESTS = "tools/protected.test.mjs";
const ROUTES_FITNESS = "python/tests/fitness/test_routes_declare_response_models.py";
const ROUTES_FITNESS_TEST = "tests/fitness/test_routes_declare_response_models.py";
const FAKE_FITNESS = "python/tests/fitness/test_tests_fake_the_model_client.py";
const FAKE_FITNESS_TEST = "tests/fitness/test_tests_fake_the_model_client.py";
const PROGRESS = "tools/progress.mjs";
const progressTest = (name) => nodeTest("tools/progress.test.mjs", name);
// The git runner the script tests build their repositories with, proved by tools/git-run.test.mjs.
const GIT_RUN = "tools/git-run.mjs";
const gitRunTest = (name) => nodeTest("tools/git-run.test.mjs", name);

export const MUTATIONS = [
  // Chapter 3, after the 2026-09-30 review: an id too big for SQLite is one that doesn't exist.
  {
    guard: "data: a ticket number too big for SQLite is a missing ticket",
    file: "python/src/helpdesk/data/repository.py",
    find: "    if ticket_id not in IDS:\n        return None\n",
    replace: "",
    run: pytest(
      "tests/test_triage_tools.py::test_a_ticket_number_too_big_for_sqlite_is_a_ticket_that_doesnt_exist",
      "tests/test_api.py::test_an_id_too_big_for_sqlite_is_one_that_does_not_exist",
    ),
  },
  {
    guard: "data: a customer id too big for SQLite is a missing customer",
    file: "python/src/helpdesk/data/repository.py",
    find: "    if customer_id not in IDS:\n        return False\n",
    replace: "",
    run: pytest("tests/test_api.py::test_an_id_too_big_for_sqlite_is_one_that_does_not_exist"),
  },
  {
    guard: "data: a staff id too big for SQLite is a missing member of staff",
    file: "python/src/helpdesk/data/repository.py",
    find: "    if staff_id not in IDS:\n        return False\n",
    replace: "",
    run: pytest("tests/test_api.py::test_an_id_too_big_for_sqlite_is_one_that_does_not_exist"),
  },
  {
    guard: "data: the ids SQLite can store are 8 bytes, signed",
    file: "python/src/helpdesk/data/repository.py",
    find: "IDS = range(-(2**63), 2**63)",
    replace: "IDS = range(-(2**63), 2**64)",
    run: pytest("tests/test_triage_tools.py::test_a_ticket_number_too_big_for_sqlite_is_a_ticket_that_doesnt_exist"),
  },

  // Chapter 16: import rules in Python.
  {
    guard: "import-linter: only helpdesk.model imports the anthropic SDK",
    file: "python/pyproject.toml",
    find: 'allowed_importers = ["helpdesk.model"]',
    replace: 'allowed_importers = ["helpdesk"]',
    run: pytest(`${LAYERS}::test_a_service_importing_the_sdk_is_caught_with_the_fix`, `${LAYERS}::test_a_module_written_after_the_contract_is_covered_too`),
  },
  {
    guard: "import-linter: the SDK contract says how to fix it",
    file: "python/pyproject.toml",
    find: 'broken_contract_guidance = "Code outside helpdesk.model must not call the vendor directly. Take a ModelClient as an argument instead, so tests can pass the mock and refusals go through helpdesk.model.stops; if the model needs something new, add it to helpdesk.model."\n',
    replace: "",
    run: pytest(`${LAYERS}::test_a_service_importing_the_sdk_is_caught_with_the_fix`),
  },
  {
    guard: "import-linter: the data-layer contract says how to fix it",
    file: "python/pyproject.toml",
    find: 'broken_contract_guidance = "Code that needs data must call a service: move the query into helpdesk.services and call that from the route or the tool."\n',
    replace: "",
    run: pytest(`${LAYERS}::test_route_importing_the_data_layer_is_caught_with_the_fix`),
  },
  {
    guard: "import-linter: installed packages are in the import graph",
    file: "python/pyproject.toml",
    find: "include_external_packages = true\n",
    replace: "",
    run: pytest(`${LAYERS}::test_clean_copy_keeps_every_contract`),
  },

  // Chapter 16: import rules in TypeScript.
  {
    guard: "dependency-cruiser: imports used only for types count",
    file: DC,
    find: "tsPreCompilationDeps: true,",
    replace: "tsPreCompilationDeps: false,",
    run: vitest("test/boundaries.test.ts", "catches an import that exists only for types"),
  },
  {
    guard: "dependency-cruiser: process.getBuiltinModule() counts as an import",
    file: DC,
    find: "detectProcessBuiltinModuleCalls: true,",
    replace: "detectProcessBuiltinModuleCalls: false,",
    run: vitest("test/boundaries.test.ts", "catches a Node built-in in the client, however it is loaded"),
  },
  {
    guard: "dependency-cruiser: the client doesn't import the CLI",
    file: DC,
    find: 'from: { path: "^src/client[.]ts$" },\n      to: { path: "^src/cli[.]ts$" },',
    replace: 'from: { path: "^nothing$" },\n      to: { path: "^src/cli[.]ts$" },',
    run: vitest("test/boundaries.test.ts", "catches the same import written as a dynamic import"),
  },
  {
    guard: "dependency-cruiser: a rule's comment says how to fix it",
    file: DC,
    find: " Move what both need into client.ts or types.ts.",
    replace: "",
    run: vitest("test/boundaries.test.ts", "catches the client importing the CLI, and says how to fix it"),
  },
  {
    guard: "dependency-cruiser: the types import nothing above them",
    file: DC,
    find: 'to: { path: "^src/(client|cli)[.]ts$" },',
    replace: 'to: { path: "^nothing$" },',
    run: vitest("test/boundaries.test.ts", "catches an import that exists only for types"),
  },
  {
    guard: "dependency-cruiser: only types.ts imports the generated file",
    file: DC,
    find: 'from: { pathNot: "^src/types[.]ts$" },',
    replace: 'from: { pathNot: "^src/(types|cli)[.]ts$" },',
    run: vitest("test/boundaries.test.ts", "catches the CLI importing the generated file directly"),
  },
  {
    guard: "dependency-cruiser: only the CLI uses Node's built-ins",
    file: DC,
    find: 'to: { dependencyTypes: ["core"] },',
    replace: 'to: { path: "^nothing$" },',
    run: vitest("test/boundaries.test.ts", "catches a Node built-in in the client, however it is loaded"),
  },
  {
    guard: "dependency-cruiser: src doesn't import scripts or tests",
    file: DC,
    find: 'to: { path: "^(scripts|test)/" },',
    replace: 'to: { path: "^nothing$" },',
    run: vitest("test/boundaries.test.ts", "catches the package importing a script"),
  },
  {
    guard: "dependency-cruiser: the folders cruised are read from the tree, not listed",
    file: "ts/test/boundaries.test.ts",
    find: "    .filter(hasTypeScript)\n",
    replace: '    .filter((name) => ["src", "scripts", "test"].includes(name))\n',
    run: vitest("test/boundaries.test.ts", "covers a folder added later"),
  },
  {
    guard: "dependency-cruiser: npm run deps cruises every folder with TypeScript in it",
    file: "ts/package.json",
    find: '"deps": "depcruise src scripts test --config',
    replace: '"deps": "depcruise src test --config',
    run: vitest("test/boundaries.test.ts", "cruises every top-level folder"),
  },
  {
    guard: "dependency-cruiser: no circular imports",
    file: DC,
    find: "to: { circular: true },",
    replace: 'to: { path: "^nothing$" },',
    run: vitest("test/boundaries.test.ts", "catches files that import each other in a circle"),
  },
  {
    guard: "dependency-cruiser: the test checks every file was read",
    file: "ts/test/boundaries.test.ts",
    find: "[DEPCRUISE, ...folders,",
    replace: '[DEPCRUISE, "src", "test",',
    run: vitest("test/boundaries.test.ts", "reads every TypeScript file in the package"),
  },
  {
    guard: "ESLint: built-ins are caught under their bare names too",
    file: ESLINT,
    find: "const NODE_BUILTINS = [...BARE, ",
    replace: "const NODE_BUILTINS = [",
    run: vitest("test/boundaries.test.ts", "under either name"),
  },
  {
    guard: "ESLint: the built-ins rule covers files written later",
    file: ESLINT,
    find: 'files: ["src/**/*.ts"],',
    replace: 'files: ["src/client.ts", "src/types.ts", "src/api-types.ts"],',
    run: vitest("test/boundaries.test.ts", "covers a file in src/ that doesn't exist yet"),
  },
  {
    guard: "ESLint: the CLI may use Node's built-ins",
    file: ESLINT,
    find: 'ignores: ["src/cli.ts"],',
    replace: "ignores: [],",
    run: vitest("test/boundaries.test.ts", "lets the CLI import them"),
  },
  {
    guard: "ESLint: every TypeScript file is linted",
    file: ESLINT,
    find: 'files: ["**/*.ts"],',
    replace: 'files: ["src/**/*.ts"],',
    run: vitest("test/boundaries.test.ts", "lints every TypeScript file in the package"),
  },

  // Chapter 17: the Python model-text rule.
  {
    guard: "HDK101: results of .complete() are tracked",
    file: MODEL_TEXT,
    find: "        if is_complete_call(value):\n            return True\n",
    replace: "        if False:\n            return True\n",
    run: pytest(`${LINT}::test_reading_the_text_after_complete_is_caught_and_the_message_says_what_to_do`),
  },
  {
    guard: "HDK101: a plain alias of a response is followed",
    file: MODEL_TEXT,
    find: "        return isinstance(value, ast.Name) and any(value.id in scope for scope in self.scopes)\n",
    replace: "        return False\n",
    run: pytest(`${LINT}::test_a_response_under_another_name_is_followed`),
  },
  {
    guard: "HDK101: each name of an unpacked tuple is followed",
    file: MODEL_TEXT,
    find: "            for t, v in zip(target.elts, value.elts, strict=True):\n                self._bind(t, v)\n",
    replace: "            pass\n",
    run: pytest(`${LINT}::test_a_response_under_another_name_is_followed`),
  },
  {
    guard: "HDK101: a name the walrus operator binds is followed",
    file: MODEL_TEXT,
    find: "binds r like an assignment.\n        self.generic_visit(node)\n        self._bind(node.target, node.value)\n",
    replace: "binds r like an assignment.\n        self.generic_visit(node)\n",
    run: pytest(`${LINT}::test_a_response_under_another_name_is_followed`),
  },
  {
    guard: "HDK101: text read straight off a walrus is caught",
    file: MODEL_TEXT,
    find: "            elif isinstance(node.value, ast.NamedExpr) and self._responds(node.value.value):",
    replace: "            elif False:",
    run: pytest(`${LINT}::test_a_response_under_another_name_is_followed`),
  },
  {
    guard: "HDK101: ModelResponse annotations are recognized",
    file: MODEL_TEXT,
    find: '        if isinstance(node, ast.Name) and node.id == "ModelResponse":',
    replace: '        if isinstance(node, ast.Name) and node.id == "NotModelResponse":',
    run: pytest(`${LINT}::test_a_parameter_annotated_as_a_model_response_is_caught`),
  },
  {
    guard: "HDK101: text read straight off the call is caught",
    file: MODEL_TEXT,
    find: "            elif is_complete_call(node.value):\n                self.reads.append",
    replace: "            elif False:\n                self.reads.append",
    run: pytest(`${LINT}::test_reading_the_text_straight_off_the_call_is_caught`),
  },
  {
    guard: "HDK101: each function has its own scope",
    file: MODEL_TEXT,
    find: "        self.scopes.append(responses)\n        self.generic_visit(node)\n        self.scopes.pop()",
    replace: "        self.scopes[-1].update(responses)\n        self.generic_visit(node)",
    run: pytest(`${LINT}::test_a_name_in_another_function_is_not_a_model_response`),
  },
  {
    guard: "HDK101: only model responses are flagged, not every .text",
    file: MODEL_TEXT,
    find: "            if isinstance(node.value, ast.Name) and any(node.value.id in scope for scope in self.scopes):",
    replace: "            if isinstance(node.value, ast.Name):",
    run: pytest(`${LINT}::test_final_text_and_other_objects_text_pass`),
  },
  {
    guard: "HDK102: an exception needs a reason",
    file: MODEL_TEXT,
    find: "        elif not exemption.reason:",
    replace: "        elif False:",
    run: pytest(`${LINT}::test_an_exception_without_a_reason_fails`),
  },
  {
    guard: "HDK103: a stale exception fails",
    file: MODEL_TEXT,
    find: "        if covered not in read_lines:\n            problems.append(Problem(exemption.line, 1, STALE))",
    replace: "        if covered not in read_lines:\n            pass",
    run: pytest(`${LINT}::test_an_exception_where_nothing_reads_the_text_fails`),
  },
  {
    guard: "HDK101: an exception may sit on the line above",
    file: MODEL_TEXT,
    find: "        covered = line + 1 if alone else line",
    replace: "        covered = line",
    run: pytest(`${LINT}::test_an_exception_with_a_reason_is_accepted_on_the_line_or_just_above_it`),
  },
  {
    guard: "HDK101: the message says what to do",
    file: MODEL_TEXT,
    find: '"recording the turn, put the reason on it: # HDK101: <why>"',
    replace: '"recording the turn."',
    run: pytest(`${LINT}::test_reading_the_text_after_complete_is_caught_and_the_message_says_what_to_do`),
  },
  {
    guard: "helpdesk_lint: a run that read no files fails",
    file: "python/src/helpdesk_lint/__main__.py",
    find: "        return 2\n",
    replace: "        return 0\n",
    run: pytest(`${LINT}::test_the_model_package_is_exempt_and_a_run_that_checks_nothing_fails`),
  },
  {
    guard: "helpdesk_lint: the model package is exempt",
    file: "python/src/helpdesk_lint/__main__.py",
    find: 'EXEMPT_PACKAGE = ("helpdesk", "model")',
    replace: 'EXEMPT_PACKAGE = ("helpdesk", "nothing")',
    run: pytest(`${LINT}::test_the_helpdesk_passes_with_one_exception_that_says_why`),
  },
  {
    guard: "helpdesk_lint: the agent loop's exception carries its reason",
    file: "python/src/helpdesk/assistant/agent.py",
    find: "        # HDK101: the turn goes into the transcript as it came; the answer goes through final_text below.\n",
    replace: "",
    run: pytest(`${LINT}::test_the_helpdesk_passes_with_one_exception_that_says_why`),
  },

  // Chapter 17: the custom ESLint rule.
  {
    guard: "cli-output-through-write: console.error is only suggested, never fixed",
    file: RULE,
    find: 'if (method === "log" && oneArgument) {',
    replace: "if (oneArgument) {",
    run: vitest("test/lint-rules.test.ts", "console.error"),
  },
  {
    guard: "cli-output-through-write: console.log is fixed",
    file: RULE,
    find: 'context.report({ node, messageId: "useWrite", data: { method }, fix: toWrite });',
    replace: 'context.report({ node, messageId: "useWrite", data: { method } });',
    run: vitest("test/lint-rules.test.ts", "console.log"),
  },
  {
    guard: "cli-output-through-write: only a write parameter counts",
    file: RULE,
    find: 'if (variable) return variable.defs.some((definition) => definition.type === "Parameter");',
    replace: "if (variable) return true;",
    run: vitest("test/lint-rules.test.ts", "const write"),
  },
  {
    guard: "cli-output-through-write: write is found in enclosing functions",
    file: RULE,
    find: "for (let current = scope; current; current = current.upper) {",
    replace: "for (let current = scope; current; current = null) {",
    run: vitest("test/lint-rules.test.ts", "fixes a console.log planted"),
  },
  {
    guard: "cli-output-through-write: the message says why",
    file: RULE,
    find: " This function takes write so that tests can read its output; console.{{method}} goes straight to the terminal, where no test sees it.",
    replace: "",
    run: vitest("test/lint-rules.test.ts", "console.log"),
  },
  {
    guard: "cli-output-through-write: the rule is switched on",
    file: ESLINT,
    find: 'rules: { "local/cli-output-through-write": "error" },',
    replace: 'rules: { "local/cli-output-through-write": "off" },',
    run: vitest("test/lint-rules.test.ts", "fixes a console.log planted"),
  },

  // Chapter 18: the policy for agent definitions.
  {
    guard: "agent policy: the cost rule",
    file: AGENT_RULES,
    find: "        if cost > cap:",
    replace: "        if False:",
    run: fixture("fail-too-many-tokens-for-the-model"),
  },
  {
    guard: "agent policy: the cost depends on the model",
    file: AGENT_RULES,
    find: 'price = Decimal(str(models[model]["output_usd_per_million"]))',
    replace: 'price = Decimal("20.0")',
    run: fixture("pass-cheaper-model-more-tokens"),
  },
  {
    guard: "agent policy: unknown fields are reported",
    file: AGENT_RULES,
    find: "        if key not in FIELDS:",
    replace: "        if False:",
    run: fixture("fail-misspelled-field"),
  },
  {
    guard: "agent policy: true isn't a number",
    file: AGENT_RULES,
    find: "    return isinstance(value, kind) and not isinstance(value, bool)",
    replace: "    return isinstance(value, kind)",
    run: fixture("fail-true-is-not-a-number"),
  },
  {
    guard: "agent policy: empty text is refused",
    file: AGENT_RULES,
    find: "        elif kind is str and not definition[key].strip():",
    replace: "        elif False:",
    run: fixture("fail-empty-prompt"),
  },
  {
    guard: "agent policy: only approved models",
    file: AGENT_RULES,
    find: "    if model is not None and model not in models:",
    replace: "    if False:",
    run: fixture("fail-model-not-approved"),
  },
  {
    guard: "agent policy: every problem is reported, not only the first",
    file: AGENT_RULES,
    find: "\n    return found\n",
    replace: "\n    return found[:1]\n",
    run: fixture("fail-several-at-once"),
  },
  {
    guard: "agent policy: only known tools",
    file: AGENT_RULES,
    find: '        elif tool not in policy["tools"]:',
    replace: "        elif False:",
    run: fixture("fail-unknown-tool"),
  },
  {
    guard: "agent policy: the turn limit",
    file: AGENT_RULES,
    find: "    elif max_turns is not None and max_turns > limit:",
    replace: "    elif False:",
    run: fixture("fail-too-many-turns"),
  },
  {
    guard: "agent policy: the turn limit itself is allowed",
    file: AGENT_RULES,
    find: "    elif max_turns is not None and max_turns > limit:",
    replace: "    elif max_turns is not None and max_turns >= limit:",
    run: fixture("pass-turns-at-the-limit"),
  },
  {
    guard: "agent policy: one turn over the limit is refused",
    file: AGENT_RULES,
    find: "    elif max_turns is not None and max_turns > limit:",
    replace: "    elif max_turns is not None and max_turns > limit + 1:",
    run: fixture("fail-turns-one-over-the-limit"),
  },
  {
    guard: "agent policy: every rule is registered",
    file: AGENT_RULES,
    find: '    "empty": "a text field left empty",\n',
    replace: "",
    run: pytest(`${POLICY}::test_every_rule_is_shown_failing_by_some_fixture`),
  },
  {
    guard: "agent policy: every rule has a failing fixture",
    file: AGENT_RULES,
    find: '    "tool": "a tool the platform doesn\'t provide",\n',
    replace: '    "tool": "a tool the platform doesn\'t provide",\n    "unused": "a rule nothing tests",\n',
    run: pytest(`${POLICY}::test_every_rule_is_shown_failing_by_some_fixture`),
  },
  {
    guard: "agent policy: the triage assistant checks before it runs",
    file: "python/src/helpdesk/triage.py",
    find: "    violations = check(agent, load(POLICY))",
    replace: "    violations = []",
    run: pytest(`${POLICY}::test_the_triage_assistant_refuses_a_definition_that_breaks_the_policy`),
  },
  {
    guard: "agent policy: the check sees this run's --max-turns",
    file: "python/src/helpdesk/triage.py",
    find: '    if args.max_turns is not None:\n        agent["max_turns"] = args.max_turns\n    violations = check(agent, load(POLICY))',
    replace: '    violations = check(agent, load(POLICY))\n    if args.max_turns is not None:\n        agent["max_turns"] = args.max_turns',
    run: pytest(`${POLICY}::test_the_triage_assistant_checks_the_turn_limit_it_is_given_too`),
  },
  {
    guard: "agent policy: its prices match the code",
    file: "python/agents/policy.toml",
    find: "claude-opus-5-5 = { output_usd_per_million = 20.0 }",
    replace: "claude-opus-5-5 = { output_usd_per_million = 15.0 }",
    run: pytest(`${POLICY}::test_the_policy_prices_match_the_code`),
  },
  {
    guard: "agent policy: its tools match the code",
    file: "python/agents/policy.toml",
    find: 'tools = ["get_ticket", "search_kb"]',
    replace: 'tools = ["get_ticket", "search_kb", "send_email"]',
    run: pytest(`${POLICY}::test_the_policy_tools_are_the_tools_the_code_provides`),
  },
  {
    guard: "agent policy: the fixtures are found",
    file: "python/tests/test_agent_policy.py",
    find: 'FIXTURES_DIR = Path(__file__).parent / "policy_fixtures"',
    replace: 'FIXTURES_DIR = Path(__file__).parent / "policy_fixture"',
    run: pytest(`${POLICY}::test_there_are_fixtures_to_run`),
  },
  {
    guard: "agent policy: a run with nothing to check fails",
    file: "python/src/agent_policy/__main__.py",
    find: "        return 2\n",
    replace: "        return 0\n",
    run: pytest(`${POLICY}::test_a_run_that_finds_no_definitions_fails`),
  },

  // Chapter 24: this runner's own guards.
  {
    guard: "mutate: a nested test command answers for itself",
    file: "tools/mutate.mjs",
    find: "delete ENV.NODE_TEST_CONTEXT;",
    replace: "",
    run: { node: ["--test", "tools/mutate.test.mjs"] },
  },
  {
    guard: "mutate: a test command must pass on the unchanged code first",
    file: "tools/mutate.mjs",
    find: 'if (controls.get(key) !== "pass") {',
    replace: "if (false) {",
    run: { node: ["--test", "tools/mutate.test.mjs"] },
  },
  {
    guard: "mutate: a mutation whose text is gone is stale",
    file: "tools/mutate.mjs",
    find: "if (text.split(m.find).length !== 2) {",
    replace: "if (false) {",
    run: { node: ["--test", "tools/mutate.test.mjs"] },
  },

  // Chapter 25: sending failures back to the agent, and the limits on doing it.
  {
    guard: "feedback: the exit code decides whether the checks passed",
    file: "tools/feedback.mjs",
    find: "return { passed: run.status === 0, output };",
    replace: 'return { passed: !output.includes("FAIL"), output };',
    run: nodeTest(FEEDBACK_TESTS, "the exit code decides"),
  },
  {
    guard: "feedback: the report leaves out the checks that passed",
    file: "tools/feedback.mjs",
    find: '.filter((line) => !line.startsWith("PASS  "))',
    replace: ".filter(() => true)",
    run: nodeTest(FEEDBACK_TESTS, "keeps the failing checks"),
  },
  {
    guard: "feedback: the report is bounded",
    file: "tools/feedback.mjs",
    find: "if (kept.length <= max) return kept;",
    replace: "return kept;",
    run: nodeTest(FEEDBACK_TESTS, "cuts a long report"),
  },
  {
    guard: "feedback: the checks run without the provider's credentials",
    file: "tools/feedback.mjs",
    find: "    env: checkEnvironment(),\n",
    replace: "",
    run: nodeTest(FEEDBACK_TESTS, "the checks run without the provider's credentials"),
  },
  {
    guard: "feedback: an auth token is held back as well as an API key",
    file: "tools/feedback.mjs",
    find: 'export const CREDENTIALS = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"];',
    replace: 'export const CREDENTIALS = ["ANTHROPIC_API_KEY"];',
    run: nodeTest(FEEDBACK_TESTS, "the checks run without the provider's credentials"),
  },
  {
    guard: "feedback: a credential's name is matched without regard to case",
    file: "tools/feedback.mjs",
    find: "if (CREDENTIALS.includes(name.toUpperCase()))",
    replace: "if (CREDENTIALS.includes(name))",
    run: nodeTest(FEEDBACK_TESTS, "the checks run without the provider's credentials"),
  },
  {
    guard: "Stop hook: a failure blocks with exit code 2",
    file: "tools/hooks/stop-decision.mjs",
    find: "return { exitCode: 2, blocks, stderr };",
    replace: "return { exitCode: 1, blocks, stderr };",
    run: nodeTest(STOP_TESTS, "a failure blocks with exit code 2"),
  },
  {
    guard: "Stop hook: three blocks in a row, then the agent may stop",
    file: "tools/hooks/stop-decision.mjs",
    find: "if (blocksSoFar >= MAX_BLOCKS) {",
    replace: "if (false) {",
    run: nodeTest(STOP_TESTS, "after three blocks in a row"),
  },
  {
    guard: "Stop hook: a session id can't choose where the count goes",
    file: "tools/hooks/stop-decision.mjs",
    find: '.replace(/[^A-Za-z0-9_-]/g, "_")',
    replace: "",
    run: nodeTest(STOP_TESTS, "a session id can't choose"),
  },
  {
    guard: "Stop hook: a stop that doesn't follow a block starts counting again",
    file: "tools/hooks/stop-check.mjs",
    find: "const blocksSoFar = input.stop_hook_active ? readBlocks(file) : 0;",
    replace: "const blocksSoFar = readBlocks(file);",
    run: nodeTest(STOP_TESTS, "a stop that doesn't follow a block"),
  },
  {
    guard: "Stop hook: the checks run where the agent is working",
    file: "tools/hooks/stop-check.mjs",
    find: "repositoryRoot(input.cwd ?? process.cwd())",
    replace: "repositoryRoot(process.cwd())",
    run: nodeTest(STOP_TESTS, "a failure blocks with exit code 2"),
  },
  {
    guard: "Stop hook: .claude/settings.json runs a script that exists",
    file: ".claude/settings.json",
    find: '"${CLAUDE_PROJECT_DIR}/tools/hooks/stop-check.mjs"',
    replace: '"${CLAUDE_PROJECT_DIR}/tools/hook/stop-check.mjs"',
    run: nodeTest(STOP_TESTS, "every command hook"),
  },
  {
    guard: "fix loop: the prompt carries the report",
    file: "tools/fix-loop.mjs",
    find: "    failureReport(output),\n",
    replace: '    "(see the checks)",\n',
    run: nodeTest(LOOP_TESTS, "the prompt carries the report"),
  },
  {
    guard: "fix loop: at most the set number of attempts",
    file: "tools/fix-loop.mjs",
    find: "for (let attempt = 1; attempt <= attempts; attempt++) {",
    replace: "for (let attempt = 1; attempt <= attempts + 1; attempt++) {",
    run: nodeTest(LOOP_TESTS, "stops after three attempts"),
  },
  {
    guard: "fix loop: an attempt that changes nothing ends the loop",
    file: "tools/fix-loop.mjs",
    find: "if (withoutTimes(checks.output) === withoutTimes(previous.output)) {",
    replace: "if (false) {",
    run: nodeTest(LOOP_TESTS, "stops at once when an attempt"),
  },
  {
    guard: "fix loop: a change to the checks stops the loop",
    file: "tools/fix-loop.mjs",
    find: "  if (changed.length) {",
    replace: "  if (false) {",
    run: nodeTest(LOOP_TESTS, "stops when the agent changes the checks"),
  },
  {
    guard: "fix loop: check.mjs counts as one of the checks",
    file: PROTECTED_MJS,
    find: "export const ALWAYS = [/^check\\.mjs$/, TOOLS,",
    replace: "export const ALWAYS = [TOOLS,",
    run: nodeTest(LOOP_TESTS, "stops when the agent changes the checks"),
  },

  // Chapter 31: the rework count.
  {
    guard: "rework: a co-author trailer naming an agent counts",
    file: REWORK,
    find: "/\\b(claude|copilot|codex|cursor|devin|gemini|aider|windsurf|jules)\\b/i",
    replace: "/\\b(copilot|codex|cursor|devin|gemini|aider|windsurf|jules)\\b/i",
    run: nodeTest(REWORK_TESTS, "counts agent commits"),
  },
  {
    guard: "rework: so does an agent as the author",
    file: REWORK,
    find: "AGENT.test(commit.author) || ",
    replace: "",
    run: nodeTest(REWORK_TESTS, "counts agent commits"),
  },
  {
    guard: "rework: fixed and fixes count as fixes",
    file: REWORK,
    find: "/^(fix(es|ed)?|hotfix|revert(s|ed)?)\\b/i",
    replace: "/^(fix|hotfix|revert)\\b/i",
    run: nodeTest(REWORK_TESTS, "fix subjects"),
  },
  {
    guard: "rework: a fix to a person's change isn't rework",
    file: REWORK,
    find: "return before && before.agent && commit.time - before.time < within * DAY;",
    replace: "return before && commit.time - before.time < within * DAY;",
    run: nodeTest(REWORK_TESTS, "a fix to a person's change"),
  },
  {
    guard: "rework: nor is a fix to an old agent change",
    file: REWORK,
    find: "return before && before.agent && commit.time - before.time < within * DAY;",
    replace: "return before && before.agent;",
    run: nodeTest(REWORK_TESTS, "a fix to a person's change"),
  },
  {
    guard: "rework: the history reaches back before the window",
    file: REWORK,
    find: "readHistory(root, windowStart - within * DAY, { allFiles, ignore })",
    replace: "readHistory(root, windowStart, { allFiles, ignore })",
    run: nodeTest(REWORK_TESTS, "an agent change just before the window"),
  },
  {
    guard: "rework: Markdown files are left out",
    file: REWORK,
    find: "(allFiles || !MARKDOWN.test(f))",
    replace: "true",
    run: nodeTest(REWORK_TESTS, "Markdown files don't make a fix rework"),
  },
  {
    guard: "rework: --ignore leaves files out",
    file: REWORK,
    find: "!(ignore && ignore.test(f))",
    replace: "true",
    run: nodeTest(REWORK_TESTS, "--ignore leaves out files"),
  },
  {
    guard: "rework: a fix counts once per folder",
    file: REWORK,
    find: "for (const name of new Set(reworked.map((f) => folder(f, depth)))) {",
    replace: "for (const name of reworked.map((f) => folder(f, depth))) {",
    run: nodeTest(REWORK_TESTS, "folders are grouped"),
  },
  {
    guard: "rework: folders go --depth levels deep",
    file: REWORK,
    find: 'parts.slice(0, depth).join("/")',
    replace: 'parts.slice(0, 1).join("/")',
    run: nodeTest(REWORK_TESTS, "folders are grouped"),
  },

  // Chapter 9: retrieval over the knowledge base, its golden-set check, and citation checking.
  {
    guard: "retrieval: every passage carries its article's title and heading",
    file: RETRIEVAL,
    find: 'return f"{self.title} > {self.heading}: {self.text}" if self.heading else f"{self.title}: {self.text}"',
    replace: "return self.text",
    run: pytest(`${RETRIEVAL_TESTS}::test_a_question_can_find_a_passage_through_its_heading`),
  },
  {
    guard: "retrieval: BM25 marks down a longer passage",
    file: RETRIEVAL,
    find: "norm = K1 * (1 - B + B * length / self.average_length)",
    replace: "norm = K1",
    run: pytest(`${RETRIEVAL_TESTS}::test_bm25_marks_down_a_longer_passage_with_the_same_matches`),
  },
  {
    guard: "retrieval: a word in most passages weighs nothing, never less",
    file: RETRIEVAL,
    find: "max(0.0, math.log((n - c + 0.5) / (c + 0.5)))",
    replace: "math.log((n - c + 0.5) / (c + 0.5))",
    run: pytest(`${RETRIEVAL_TESTS}::test_a_word_in_most_passages_adds_nothing_rather_than_counting_against_a_passage`),
  },
  {
    guard: "retrieval: fusion's k = 60 lets agreement beat one ranker's first place",
    file: RETRIEVAL,
    find: "RRF_K = 60",
    replace: "RRF_K = 0",
    run: pytest(`${RETRIEVAL_TESTS}::test_fusion_puts_a_passage_both_rankers_like_above_one_only_a_single_ranker_puts_first`),
  },
  {
    guard: "retrieval: keyword search returns only passages with a word in common",
    file: RETRIEVAL,
    find: "passing = [i for i, s in enumerate(scores) if s > 0]",
    replace: "passing = list(range(len(scores)))",
    run: pytest(`${RETRIEVAL_TESTS}::test_a_question_the_knowledge_base_cannot_answer_gets_nothing_back`),
  },
  {
    guard: "retrieval: the vector ranker returns only passages above its floor",
    file: RETRIEVAL,
    find: "passing = [i for i, s in enumerate(scores) if s >= VECTOR_FLOOR]",
    replace: "passing = list(range(len(scores)))",
    run: pytest(`${RETRIEVAL_TESTS}::test_a_question_the_knowledge_base_cannot_answer_gets_nothing_back`),
  },
  {
    guard: "retrieval eval: recall below the floor fails",
    file: KB_CLI,
    find: 'recall_ok = hybrid.recall >= floor["recall"]',
    replace: "recall_ok = True",
    run: pytest(`${KB_CLI_TESTS}::test_the_eval_fails_when_retrieval_loses_a_question_and_names_it`),
  },
  {
    guard: "retrieval eval: passages for a question with no answer fail",
    file: KB_CLI,
    find: 'empty_ok = empty_share >= floor["no_answer_empty"]',
    replace: "empty_ok = True",
    run: pytest(`${KB_CLI_TESTS}::test_the_eval_fails_when_a_question_with_no_answer_gets_passages`),
  },
  {
    guard: "retrieval eval: a hit must contain the answer, not just come from the right article",
    file: KB_CLI,
    find: 'return any(h.chunk.article_id == answer["article"] and says in h.chunk.text.lower() for h in hits)',
    replace: 'return any(h.chunk.article_id == answer["article"] for h in hits)',
    run: pytest(`${KB_CLI_TESTS}::test_a_passage_from_the_right_article_without_the_answer_is_a_miss`),
  },
  {
    guard: "citations: a citation to a passage that doesn't exist is caught",
    file: CITATIONS,
    find: "if known is not None and citation not in known:",
    replace: "if False:",
    run: pytest(`${CITATIONS_TESTS}::test_a_citation_to_a_passage_that_does_not_exist_is_caught`),
  },
  {
    guard: "citations: a citation to a passage the answer wasn't given is caught",
    file: CITATIONS,
    find: `            elif citation not in given:
                reason = f"[{citation}] wasn't among the passages this answer was given"
                problems.append(Problem(citation, sentence, f"{reason}, so it can't have come from it"))
            else:
                support |= _vocabulary(given[citation])`,
    replace: `            else:
                support |= _vocabulary(given.get(citation, ""))`,
    run: pytest(`${CITATIONS_TESTS}::test_a_citation_to_a_real_passage_the_answer_was_not_given_is_caught`),
  },
  {
    guard: "citations: a sentence using words its passages don't have is caught",
    file: CITATIONS,
    find: "if support and missing:",
    replace: "if False:",
    run: pytest(`${CITATIONS_TESTS}::test_a_changed_fact_is_caught_and_the_word_named`),
  },
  {
    guard: "citations: a citation after the full stop belongs to the sentence before it",
    file: CITATIONS,
    find: "        if lead and found:",
    replace: "        if False:",
    run: pytest(
      `${CITATIONS_TESTS}::test_a_citation_after_the_full_stop_at_the_end_is_checked_against_its_sentence`,
      `${CITATIONS_TESTS}::test_a_citation_after_the_full_stop_mid_answer_stays_with_its_own_sentence`,
    ),
  },
  {
    guard: "citations: a run of citations after the full stop goes back whole",
    file: CITATIONS,
    find: 'LEADING_CITATIONS = re.compile(r"^(?:\\s*[(,;]?\\s*\\[\\d+#\\d+\\]\\s*\\)?)+")',
    replace: 'LEADING_CITATIONS = re.compile(r"^(?:\\s*[(,;]?\\s*\\[\\d+#\\d+\\]\\s*\\)?)")',
    run: pytest(`${CITATIONS_TESTS}::test_citations_after_the_full_stop_all_go_back_to_the_sentence_they_follow`),
  },
  {
    guard: "citations: a citation in parentheses after the full stop goes back too",
    file: CITATIONS,
    find: 'LEADING_CITATIONS = re.compile(r"^(?:\\s*[(,;]?\\s*\\[\\d+#\\d+\\]\\s*\\)?)+")',
    replace: 'LEADING_CITATIONS = re.compile(r"^(?:\\s*[,;]?\\s*\\[\\d+#\\d+\\]\\s*)+")',
    run: pytest(`${CITATIONS_TESTS}::test_a_citation_after_the_full_stop_at_the_end_is_checked_against_its_sentence`),
  },
  {
    guard: "citations: a citation with no sentence to support is a problem",
    file: CITATIONS,
    find: '        if not words(CITATION.sub(" ", sentence)):',
    replace: "        if False:",
    run: pytest(`${CITATIONS_TESTS}::test_a_citation_with_no_sentence_to_support_is_a_problem`),
  },
  {
    guard: "citations: the messages say the check compares words, not meaning",
    file: KB_CLI,
    find: `"and uses only its passage's words."`,
    replace: `"and supports its sentence."`,
    run: pytest(`${KB_CLI_TESTS}::test_cite_passes_a_supported_answer_and_fails_a_changed_fact`),
  },
  {
    guard: "triage: a draft whose citations fail is reported as failing",
    file: "python/src/helpdesk/triage.py",
    find: "    return report.ok\n",
    replace: "    return True\n",
    run: pytest("tests/test_triage_cli.py::test_a_draft_that_changes_what_its_passage_says_is_stopped"),
  },

  // The fix loop's protected list, derived from the checks (a review, 2026-09-26): each check's code
  // and data, a tool's configuration anywhere, file-wide silencing, and HEAD watched.
  {
    guard: "fix loop: every check's listed files feed the protected list",
    file: PROTECTED_MJS,
    find: "export const PROTECTED = [...ALWAYS, ...new Set(Object.values(CHECK_FILES).flat()), CONFIG_NAMES];",
    replace: "export const PROTECTED = [...ALWAYS, CONFIG_NAMES];",
    run: nodeTest(LOOP_TESTS, "the checks' records and data stop the loop"),
  },
  {
    guard: "fix loop: a check without its files listed fails the test",
    file: PROTECTED_MJS,
    find: '  "Agent definitions (python -m agent_policy)": [',
    replace: '  "Agent definitions": [',
    run: nodeTest(PROTECTED_TESTS, "every check node check.mjs runs has its files listed"),
  },
  {
    guard: "fix loop: what check.mjs runs is covered (the API contract's module)",
    file: PROTECTED_MJS,
    find: "[/^python\\/src\\/helpdesk\\/contract\\.py$/]",
    replace: "[]",
    run: nodeTest(PROTECTED_TESTS, "what check.mjs runs is protected"),
  },
  {
    guard: "fix loop: a new ruff.toml is a change to the checks, in any folder",
    file: PROTECTED_MJS,
    find: "      String.raw`\\.?ruff\\.toml`,\n",
    replace: "",
    run: nodeTest(LOOP_TESTS, "a new tool configuration file stops the loop"),
  },
  {
    guard: "fix loop: a .gitignore is a change to the checks",
    file: PROTECTED_MJS,
    find: "      String.raw`\\.gitignore`,\n",
    replace: "",
    run: nodeTest(LOOP_TESTS, "hiding a new configuration file from git"),
  },
  {
    guard: "fix loop: git's info/exclude is watched",
    file: "tools/fix-loop.mjs",
    find: 'const GIT_OWN = ["info/exclude", "config"];',
    replace: 'const GIT_OWN = ["config"];',
    run: nodeTest(LOOP_TESTS, "hiding a new configuration file from git"),
  },
  {
    guard: "fix loop: an attempt that moves HEAD stops the loop",
    file: "tools/fix-loop.mjs",
    find: "  const moved = now !== start;",
    replace: "  const moved = false;",
    run: nodeTest(LOOP_TESTS, "a commit stops the loop"),
  },
  {
    guard: "fix loop: the prompt says a commit stops the run",
    file: "tools/fix-loop.mjs",
    find: " A commit, or a checkout of another commit, stops the run too.",
    replace: "",
    run: nodeTest(LOOP_TESTS, "the prompt says a commit stops the run"),
  },

  // Chapter 15's two structural checks, fixed after a review (2026-09-26): routers under any name,
  // and no real import of the anthropic SDK under tests/.
  {
    guard: "fitness: a router under another name is followed",
    file: ROUTES_FITNESS,
    find: "            if builds_one(value) or (isinstance(value, ast.Name) and value.id in names):",
    replace: "            if False:",
    run: pytest(`${ROUTES_FITNESS_TEST}::test_a_router_under_any_name_or_import_alias_is_followed`),
  },
  {
    guard: "fitness: an import alias of APIRouter is followed",
    file: ROUTES_FITNESS,
    find: "            constructors |= {alias.asname or alias.name for alias in node.names if alias.name in CONSTRUCTORS}",
    replace: "            constructors |= set()",
    run: pytest(`${ROUTES_FITNESS_TEST}::test_a_router_under_any_name_or_import_alias_is_followed`),
  },
  {
    guard: "fitness: a router made through the fastapi module is followed",
    file: ROUTES_FITNESS,
    find: "        return isinstance(func, ast.Attribute) and func.attr in CONSTRUCTORS and _root(func) in modules",
    replace: "        return False",
    run: pytest(`${ROUTES_FITNESS_TEST}::test_a_router_under_any_name_or_import_alias_is_followed`),
  },
  {
    guard: "fitness: a copy of a router is a router",
    file: ROUTES_FITNESS,
    find: "(isinstance(value, ast.Name) and value.id in names)",
    replace: "False",
    run: pytest(`${ROUTES_FITNESS_TEST}::test_a_router_under_any_name_or_import_alias_is_followed`),
  },
  {
    guard: "fitness: a route added with add_api_route is checked",
    file: ROUTES_FITNESS,
    find: '_on_a_router(node.func, routers, {"add_api_route"})',
    replace: "_on_a_router(node.func, routers, set())",
    run: pytest(`${ROUTES_FITNESS_TEST}::test_a_router_under_any_name_or_import_alias_is_followed`),
  },
  {
    guard: "fitness: every module in the helpdesk is read for routes",
    file: ROUTES_FITNESS,
    find: '        for path in sorted(HELPDESK.rglob("*.py"))',
    replace: '        for path in [HELPDESK / "api" / "app.py"]',
    run: pytest(`${ROUTES_FITNESS_TEST}::test_every_route_that_returns_data_declares_its_response_model`),
  },
  {
    guard: "fitness: import anthropic in a test is caught",
    file: FAKE_FITNESS,
    find: "            found = any(_is_anthropic(alias.name) for alias in node.names)",
    replace: "            found = False",
    run: pytest(`${FAKE_FITNESS_TEST}::test_every_way_to_reach_the_sdk_starts_with_an_import_that_is_caught`),
  },
  {
    guard: "fitness: from anthropic import in a test is caught",
    file: FAKE_FITNESS,
    find: "            found = node.level == 0 and _is_anthropic(node.module)",
    replace: "            found = False",
    run: pytest(`${FAKE_FITNESS_TEST}::test_every_way_to_reach_the_sdk_starts_with_an_import_that_is_caught`),
  },
  {
    guard: "fitness: the SDK loaded by name in a test is caught",
    file: FAKE_FITNESS,
    find: 'LOADERS = {"import_module", "__import__", "importorskip"}',
    replace: "LOADERS = set()",
    run: pytest(`${FAKE_FITNESS_TEST}::test_every_way_to_reach_the_sdk_starts_with_an_import_that_is_caught`),
  },
  {
    guard: "fitness: a module whose name only starts with anthropic isn't the SDK",
    file: FAKE_FITNESS,
    find: 'return bool(name) and name.split(".")[0] == "anthropic"',
    replace: 'return bool(name) and name.startswith("anthropic")',
    run: pytest(`${FAKE_FITNESS_TEST}::test_a_string_that_mentions_the_sdk_is_not_an_import`),
  },

  // Chapter 10's done check, fixed after a review (2026-09-26): a proof must be a test the runners
  // collect, found in the code, not in a string or a comment.
  {
    guard: "progress: a Python proof must be a test_*.py file",
    file: PROGRESS,
    find: "    if (!PYTHON_TEST_FILE.test(file) || (under.length && !under.some((folder) => file.startsWith(folder)))) {",
    replace: "    if (false) {",
    run: progressTest("a proof that no test runner collects fails"),
  },
  {
    guard: "progress: a Python proof must be under pytest's testpaths",
    file: PROGRESS,
    find: "    if (!PYTHON_TEST_FILE.test(file) || (under.length && !under.some((folder) => file.startsWith(folder)))) {",
    replace: "    if (!PYTHON_TEST_FILE.test(file)) {",
    run: progressTest("real tests beside the decoys still pass"),
  },
  {
    guard: "progress: a Python proof's name starts with test",
    file: PROGRESS,
    find: "    if (!/^test\\w*$/.test(name)) return",
    replace: "    if (false) return",
    run: progressTest("a proof that no test runner collects fails"),
  },
  {
    guard: "progress: a def in a Python string or comment isn't a test",
    file: PROGRESS,
    find: "    const { code } = scan(text, true);",
    replace: "    const code = text;",
    run: progressTest("a proof that no test runner collects fails"),
  },
  {
    guard: "progress: a Python test is a def at the top of the file",
    file: PROGRESS,
    find: "new RegExp(`^(async\\\\s+)?def ${escape(name)}\\\\(`, \"m\")",
    replace: "new RegExp(`^\\\\s*(async\\\\s+)?def ${escape(name)}\\\\(`, \"m\")",
    run: progressTest("a proof that no test runner collects fails"),
  },
  {
    guard: "progress: a JavaScript or TypeScript proof must be a test file",
    file: PROGRESS,
    find: "  if (!SCRIPT_TEST_FILE.test(file)) {",
    replace: "  if (false) {",
    run: progressTest("a proof that no test runner collects fails"),
  },
  {
    guard: "progress: a JavaScript title in a comment isn't a test",
    file: PROGRESS,
    find: '    if (python ? c === "#" : text.startsWith("//", i)) {',
    replace: '    if (python ? c === "#" : false) {',
    run: progressTest("a proof that no test runner collects fails"),
  },
  {
    guard: "progress: a JavaScript title inside another string isn't a test",
    file: PROGRESS,
    find: "    } else if (c === '\"' || c === \"'\" || (!python && c === \"`\")) {",
    replace: "    } else if (c === '\"' || (!python && c === \"`\")) {",
    run: progressTest("a proof that no test runner collects fails"),
  },
  {
    guard: "progress: a JavaScript regular expression isn't a test",
    file: PROGRESS,
    find: '    } else if (!python && c === "/" && ',
    replace: '    } else if (false && c === "/" && ',
    run: progressTest("a proof that no test runner collects fails"),
  },
  {
    guard: "pytest: an expected failure that passes fails the run",
    file: "python/pyproject.toml",
    find: "xfail_strict = true",
    replace: "xfail_strict = false",
    run: pytest("tests/test_pytest_settings.py::test_an_expected_failure_that_passes_fails_the_run"),
  },

  // Chapter 1: the tally counts only data it can trust.
  {
    guard: "tally: a missing field that may be null stops the run",
    file: "postings/tally.mjs",
    find: "      if (!(key in p)) problems.push(",
    replace: "      if (false) problems.push(",
    run: nodeTest("postings/tally.test.mjs", "a missing or misspelled field that may be null"),
  },
  // Chapter 1, the sample extended: the gateway signal, and the fields that date each posting.
  {
    guard: "tally: the gateway is checked like every other signal",
    file: "postings/tally.mjs",
    find: '  "gateway",\n];',
    replace: "];",
    run: nodeTest("postings/tally.test.mjs", "a missing gateway code stops the run"),
  },
  {
    guard: "tally: every posting has the day it was read",
    file: "postings/tally.mjs",
    find: "    if (!isDate(p.readOn)) {",
    replace: "    if (false) {",
    run: nodeTest("postings/tally.test.mjs", "a posting without its read date stops the run"),
  },
  {
    guard: "tally: a gateway basis is text, reread or note",
    file: "postings/tally.mjs",
    find: 'if ("gatewayBasis" in p && !GATEWAY_BASIS.includes(p.gatewayBasis)) {',
    replace: "if (false) {",
    run: nodeTest("postings/tally.test.mjs", "a gateway basis must be text, reread or note"),
  },
  {
    guard: "tally: an architect title says whether public work is asked for",
    file: "postings/tally.mjs",
    find: 'if ((isArchitect(p) || "publicWorkAsked" in p) && ',
    replace: 'if (("publicWorkAsked" in p) && ',
    run: nodeTest("postings/tally.test.mjs", "an architect title without publicWorkAsked"),
  },
  {
    guard: "tally: every exclusion record has the day it was screened",
    file: "postings/tally.mjs",
    find: "    if (isDate(e?.screenedOn)) return;",
    replace: "    return;",
    run: nodeTest("postings/tally.test.mjs", "an exclusion record without its screening date"),
  },

  // Chapter 7: the client's consumer test calls every method the client has.
  {
    guard: "contract: a client method no consumer test calls fails",
    file: "ts/src/client.ts",
    find: "  searchKb(query: string, limit = 5): Promise<KbArticle[]> {",
    replace: '  reopenTicket(id: number): Promise<Ticket> {\n    return this.#request("POST", `/tickets/${id}/reopen`);\n  }\n\n  searchKb(query: string, limit = 5): Promise<KbArticle[]> {',
    run: vitest("test/contract.test.ts", "calls every method the client has"),
  },
  // Chapter 7, after the 2026-09-30 review: the contract says what generated it.
  {
    guard: "contract: the contract says what made it",
    file: "python/src/helpdesk/contract.py",
    find: '    return {**doc, "info": {**doc["info"], "x-generated-by": GENERATED_BY}}',
    replace: "    return doc",
    run: pytest("tests/test_contract.py::test_the_contract_says_what_made_it_in_its_first_lines"),
  },

  // The script tests' git runner (tools/git-run.mjs): the caller's git setup stays out, a failure
  // carries what git printed, and only a file another program held open is tried again.
  {
    guard: "git-run: the caller's GIT_ variables are dropped",
    file: GIT_RUN,
    find: "    if (!/^GIT_/i.test(name) && !/^XDG_CONFIG_HOME$/i.test(name)) env[name] = value;",
    replace: "    env[name] = value;",
    run: gitRunTest("the caller's git configuration and GIT_ variables"),
  },
  {
    guard: "git-run: a failure carries git's stdout",
    file: GIT_RUN,
    find: '\\n--- stdout ---\\n${run.stdout ?? ""}',
    replace: "",
    run: gitRunTest("a failed call throws"),
  },
  {
    guard: "git-run: only a fatal error is tried again",
    file: GIT_RUN,
    find: "return status === 128 && /Permission",
    replace: "return /Permission",
    run: gitRunTest("only a file another program held open"),
  },
  {
    guard: "git-run: a commit that landed isn't run again",
    file: GIT_RUN,
    find: "/Permission denied|unable to write new index file/",
    replace: "/Permission denied|unable to write/",
    run: gitRunTest("only a file another program held open"),
  },
  {
    guard: "git-run: a lock another git holds isn't waited out",
    file: GIT_RUN,
    find: "/Permission denied|unable to write new index file/",
    replace: "/Permission denied|unable to write new index file|index\\.lock/",
    run: gitRunTest("only a file another program held open"),
  },
];
