// A custom ESLint rule (chapter 17): in a function that takes a `write` parameter, output goes
// through write, never console, so tests can read it. src/cli.ts's run() takes write for exactly
// that reason. The rule finds `write` through ESLint's scope analysis, so it applies inside nested
// callbacks too, and it fixes only what is safe: console.log(x) becomes write(x), which prints the
// same line in production and lets a test read it. For console.error and the rest it only
// suggests, because moving a line off the error stream is a decision, not a fix.
import type { Rule, Scope } from "eslint";

const METHODS = new Set(["log", "info", "warn", "error", "debug"]);

/** True when `write` resolves to a parameter of a function around this scope. */
function writeIsAParameter(scope: Scope.Scope | null): boolean {
  for (let current = scope; current; current = current.upper) {
    const variable = current.set.get("write");
    if (variable) return variable.defs.some((definition) => definition.type === "Parameter");
  }
  return false;
}

const rule: Rule.RuleModule = {
  meta: {
    type: "problem",
    docs: { description: "In a function that takes a write parameter, send output through write so tests can read it." },
    fixable: "code",
    hasSuggestions: true,
    messages: {
      useWrite:
        "Use write(...) instead of console.{{method}}(...). This function takes write so that tests can read its output; console.{{method}} goes straight to the terminal, where no test sees it.",
      replaceWithWrite: "Replace console.{{method}} with write, which sends the line wherever write sends output.",
    },
    schema: [],
  },
  create(context) {
    return {
      CallExpression(node) {
        const callee = node.callee;
        if (callee.type !== "MemberExpression" || callee.computed) return;
        if (callee.object.type !== "Identifier" || callee.object.name !== "console") return;
        if (callee.property.type !== "Identifier" || !METHODS.has(callee.property.name)) return;
        if (!writeIsAParameter(context.sourceCode.getScope(node))) return;

        const method = callee.property.name;
        const toWrite = (fixer: Rule.RuleFixer) => fixer.replaceText(callee, "write");
        // write takes one line, so only a call with exactly one argument can be rewritten.
        const oneArgument = node.arguments.length === 1 && node.arguments[0]?.type !== "SpreadElement";
        if (method === "log" && oneArgument) {
          context.report({ node, messageId: "useWrite", data: { method }, fix: toWrite });
        } else if (oneArgument) {
          context.report({
            node,
            messageId: "useWrite",
            data: { method },
            suggest: [{ messageId: "replaceWithWrite", data: { method }, fix: toWrite }],
          });
        } else {
          context.report({ node, messageId: "useWrite", data: { method } });
        }
      },
    };
  },
};

export default rule;
