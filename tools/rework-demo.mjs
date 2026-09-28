// Builds a small git history to try tools/rework.mjs on (chapter 31's Try it).
//
//   node tools/rework-demo.mjs <new folder>
//
// Twelve dated commits by one developer, working with an agent (its commits carry a co-author
// trailer) or alone: a sign-up form, an account page, a settings page and an export, and fixes. Every commit updates the
// changelog and every fix bumps the version, the way many real projects do, which is what makes
// a first rework count misleading. The dates are fixed, so the counts are the same for everyone.
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { git as runGit } from "./git-run.mjs";

const BASE = Date.parse("2026-03-02T09:00:00Z");
const HOUR = 60 * 60 * 1000;
const AGENT = "\n\nCo-Authored-By: Claude <noreply@anthropic.com>";

// [hours after BASE, agent?, subject, files]
const COMMITS = [
  [0, true, "feat: add the sign-up form", ["client/src/signup.js"]],
  [1, true, "feat: add the sign-up route", ["server/routes/signup.js", "server/tests/signup.test.js"]],
  [1.5, false, "fix: the sign-up form loses the email field", ["client/src/signup.js"]],
  [24, true, "feat: add the account page", ["client/src/account.js"]],
  [24.75, false, "fix: the account page shows the wrong name", ["client/src/account.js"]],
  [72, true, "feat: store the sign-up date", ["server/db/schema.sql"]],
  [192, false, "fix: sign-up dates are stored in the wrong time zone", ["server/db/schema.sql"]],
  [240, true, "feat: add the settings page", ["client/src/settings.js"]],
  [241, false, "docs: explain the settings page", ["docs/settings.md"]],
  [242, true, "fix: the settings page saves twice", ["client/src/settings.js"]],
  [288, false, "feat: add the export", ["server/routes/export.js"]],
  [290, false, "fix: the export's header row", ["server/routes/export.js"]],
];

const target = process.argv[2];
if (!target) {
  console.error("Usage: node tools/rework-demo.mjs <new folder>");
  process.exit(2);
}
const root = resolve(target);
if (existsSync(root) && readdirSync(root).length) {
  console.error(`rework-demo: ${root} isn't empty; give it a new folder.`);
  process.exit(2);
}
mkdirSync(root, { recursive: true });
// Through tools/git-run.mjs: your own git settings (a hook, signing) stay out of the demo.
const git = (args, env = {}) => runGit(root, args, { env });
git(["init", "-q"]);

let version = 0;
COMMITS.forEach(([hours, agent, subject, files], i) => {
  for (const file of files) {
    mkdirSync(dirname(join(root, file)), { recursive: true });
    writeFileSync(join(root, file), `// ${subject}\n`);
  }
  writeFileSync(join(root, "CHANGELOG.md"), `# Changelog\n\n${COMMITS.slice(0, i + 1).map(([, , s]) => `- ${s}`).reverse().join("\n")}\n`);
  if (subject.startsWith("fix")) version++;
  writeFileSync(join(root, "package.json"), `${JSON.stringify({ name: "demo", version: `1.0.${version}` }, null, 2)}\n`);
  const date = new Date(BASE + hours * HOUR).toISOString();
  git(["add", "-A"]);
  git(["-c", "user.name=A Developer", "-c", "user.email=developer@example.com", "commit", "-q", "-m", subject + (agent ? AGENT : "")], {
    GIT_AUTHOR_DATE: date,
    GIT_COMMITTER_DATE: date,
  });
});
console.log(`Built a demo history of ${COMMITS.length} commits in ${root}.`);
console.log(`Next: node tools/rework.mjs ${target} --all-files`);
