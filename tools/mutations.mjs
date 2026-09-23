// The guards this repository breaks on purpose, for tools/mutate.mjs (chapter 24). Each entry
// names the guard, the file and the exact text to change, what to change it to, and the test
// command that must then fail. Add entries when a chapter adds a guard. Chapters 16 to 18 are
// here; the guards from earlier chapters were broken by hand when they were built (CHANGELOG.md
// records each time) and are the next candidates to add.

const pytest = (...tests) => ({ cwd: "python", python: ["-m", "pytest", "-q", "-p", "no:cacheprovider", ...tests] });
const vitest = (file, name) => ({ cwd: "ts", vitest: [file, "-t", name] });

const LAYERS = "tests/guardrails/test_layers_contract.py";
const LINT = "tests/test_helpdesk_lint.py";
const POLICY = "tests/test_agent_policy.py";
const fixture = (name) => pytest(`${POLICY}::test_each_fixture_gets_exactly_the_verdict_it_names[${name}]`);
const DC = "ts/.dependency-cruiser.cjs";
const ESLINT = "ts/eslint.config.js";
const RULE = "ts/scripts/eslint-rules/cli-output-through-write.ts";
const MODEL_TEXT = "python/src/helpdesk_lint/model_text.py";
const AGENT_RULES = "python/src/agent_policy/rules.py";

export const MUTATIONS = [
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
    guard: "dependency-cruiser: no circular imports",
    file: DC,
    find: "to: { circular: true },",
    replace: 'to: { path: "^nothing$" },',
    run: vitest("test/boundaries.test.ts", "catches files that import each other in a circle"),
  },
  {
    guard: "dependency-cruiser: the test checks every file was read",
    file: "ts/test/boundaries.test.ts",
    find: "[DEPCRUISE, ...FOLDERS,",
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
    find: "        if is_complete_call(node.value):\n            self.scopes[-1].update(",
    replace: "        if False and is_complete_call(node.value):\n            self.scopes[-1].update(",
    run: pytest(`${LINT}::test_reading_the_text_after_complete_is_caught_and_the_message_says_what_to_do`),
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
];
