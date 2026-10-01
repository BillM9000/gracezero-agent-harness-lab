# The Zero to Prod kit

Every file the path from a request to production produces (Appendix B), in the order the stages produce them: **Ask**, **Agree**, **Ship**, **Prove**. Each comes in three forms: the skeleton to copy, a filled example, and the check that proves it. A skeleton's lines to change are marked `<...>` in text and `TEMPLATE:` in code; checked as it stands, a skeleton fails only for those, and its filled example passes. `tools/templates.test.mjs` proves every one, in `node check.mjs`.

Copy what you need. The kit is MIT-licensed, like the rest of this repository (`LICENSE`).

## Ask

| File | Skeleton | Filled example | The check |
|---|---|---|---|
| Intake brief: the questions a request must answer, and the three the gap check adds | `templates/ask/intake-brief.md` | `templates/ask/intake-brief.example.md` | `node tools/kit.mjs doc TEMPLATE FILE` |
| Gap list and decisions record: each gap, who decides it (template, build or owner), the decision and the day | `templates/ask/gaps.json` | `templates/ask/gaps.example.json` | `node tools/kit.mjs decisions FILE`; `--decided` fails while any gap is open |

The gap check writes the gap list from a brief: `python -m helpdesk.spec_review BRIEF --out GAPS.json`, from `python/`. It sends the brief to two reviewers on two providers' models (`python/agents/spec-reviewer-a.toml`, on Anthropic's; `spec-reviewer-b.toml`, on OpenAI's), on the mock unless given `--real` and `--max-usd` with each provider's credential in the environment, and a person turns what they find into decisions.

## Agree

| File | Skeleton | Filled example | The check |
|---|---|---|---|
| Project spec: what it is, who for, sources of truth, hard rules, out of scope, order of work, dated decisions | `templates/agree/project-spec.md` | `templates/agree/project-spec.example.md` | `node tools/kit.mjs doc TEMPLATE FILE` |
| Locked spec: features with stable ids, each with its decision and its proof test | `templates/agree/features.json` | `templates/agree/features.example.json` | `node tools/features-lock.mjs FILE`, which also writes the states document with `--write` |
| States document, generated from the locked spec | written by `--write` | `templates/agree/states.example.md` | the same command fails when it's stale |

## Ship

| File | Skeleton | Filled example | The check |
|---|---|---|---|
| Instructions for coding agents | `templates/AGENTS.md.template`, `templates/CLAUDE.md.template` | `AGENTS.md`, `CLAUDE.md` | `node tools/instruction-files.mjs PATH --max-tokens 4000` |
| The same at the user level, for every project on one machine (for Claude Code, `~/.claude/CLAUDE.md`; for Codex CLI, a global `AGENTS.md`): invariants, destructive operations, secrets, reporting, hooks, session start, its budget | `templates/ship/user-CLAUDE.md` | `templates/ship/user-CLAUDE.example.md`, an invented engineer's | `node tools/kit.mjs doc TEMPLATE FILE`, and `node tools/instruction-files.mjs FOLDER --max-tokens 4000` on a folder holding only a copy named `CLAUDE.md` |
| A skill: a folder with its `SKILL.md` (name, description, when it applies, steps, references) | `templates/ship/skills/your-skill-name/SKILL.md` | `.claude/skills/add-a-guard/` | `node tools/kit.mjs skill FOLDER` |
| The destructive-command guard: its settings wiring, with deny rules, and its rules file | `templates/ship/hooks/guard.json`, `templates/ship/hooks/guard-rules.mjs` | `.claude/settings.json`, `tools/hooks/destructive-guard.mjs`, `tools/hooks/guard-rules.mjs` | the templates' tests run the lab's guard with the skeleton's rules |
| The Stop hook's wiring | `templates/ship/hooks/stop.json` | `.claude/settings.json`, `tools/hooks/stop-check.mjs` | the templates' tests run the hook through the wiring |
| The settings file that wires both | `templates/ship/hooks/settings.json` | `.claude/settings.json` | the templates' tests: the two pieces, merged, and the lab's own file |
| Work list and session log | `templates/progress/features.json`, `templates/progress/log.md` | `progress/features.json`, `progress/log.md` | `node tools/progress.mjs PATH` |
| Handoff: done with evidence, not done, next, known issues | `templates/ship/handoff.md` | `templates/ship/handoff.example.md` | `node tools/kit.mjs doc TEMPLATE FILE` |
| Changelog convention | `templates/ship/CHANGELOG-convention.md` | `CHANGELOG.md` | `node tools/kit.mjs changelog FILE` |
| Change record: what, why, impact, dry run, rollback, gates | `templates/ship/change-record.md` | `templates/ship/change-record.example.md` | `node tools/kit.mjs doc TEMPLATE FILE` |
| Release card and deploy declaration: what ships, its gates, and the commit, environment, who signed and when | `templates/ship/release-card.md` | `templates/ship/release-card.example.md` | `node tools/kit.mjs doc TEMPLATE FILE` |
| Runbook, with a section for each stage | `templates/ship/runbook.md` | `templates/ship/runbook.example.md` | `node tools/kit.mjs doc TEMPLATE FILE`: a section marked `[from STAGE]` waits for that stage |
| CI workflows | `templates/workflows/` | `.github/workflows/` | the templates' tests hold each to the lab's own workflow |
| A custom lint rule | `templates/lint_rule.py` | `python/src/helpdesk_lint/` | the templates' tests: it agrees with the lab's rule |
| A fitness test | `templates/test_fitness.py` | `python/tests/fitness/test_routes_declare_response_models.py` | it passes on the lab's routes, with pytest |

## Prove

| File | Skeleton | Filled example | The check |
|---|---|---|---|
| Claims, and the proof page measured from them: pass, fail or unknown, and when | `templates/prove/claims.json` | `templates/prove/claims.example.json`, `templates/prove/proof.example.md` | `node tools/claims.mjs FILE` measures each claim and writes the page |
| A judge's rubric | `templates/rubric.json` | `python/evals/rubrics/` | the judge's own loader, `load_rubric` |
| The readiness rubric and checklist | in the lab, not copied here | `python/usecases/rubric.toml`, `python/usecases/readiness.toml` | `python -m helpdesk.readiness check` |
| Assessment checklist for a harness someone else built | `templates/assessment-checklist.md` | none: it's for a person, and no code runs it | none |
