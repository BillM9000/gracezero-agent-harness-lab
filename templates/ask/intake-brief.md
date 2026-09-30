# Intake brief: <the request, in a few words>

<!-- Ask. The questions a request must answer before anyone agrees to build it. Answer each in
plain words; "not known yet" is an answer, and the gap check turns it into a question for someone.
The three questions under "What it touches" are chapter 28's intake rubric
(python/usecases/rubric.toml), so the answers set the request's tier. Check a filled brief with:
node tools/kit.mjs doc templates/ask/intake-brief.md YOUR-BRIEF.md -->

**Asked by:** <name, team>. **Date:** <YYYY-MM-DD>.

## The problem

<What goes wrong today, for whom, and how often. A number if you have one.>

## Who it's for

<The people who use the result, and the people who approve what it does.>

## What done looks like

<What a person or a check can observe once it works. Not "it's better": what changes, and how you'd know.>

## What it touches

- What does it do with what it finds? <reads, drafts or changes>
- What's the most sensitive data it reads? <public, internal or customer>
- Who reads what it writes before a person has checked it? <staff or customers>
- <The systems it reads from and writes to.>

## What it must never do

- <A thing that would be a failure even if everything else worked.>

## Constraints

<Deadline, budget for model calls, the models or vendors allowed, where it runs.>

## Sources of truth

<Where the facts it relies on live, in order: which document or system wins when two disagree.>

## Out of scope

- <What someone might expect it to do, and it won't.>

## Follow-up questions from the gap check

<!-- The gap check reads this brief and lists what it leaves open.
Copy its three most important questions here with their answers; the rest stay in the gap list. -->

1. <A question the gap check asked> <Its answer, and who gave it.>
2. <A question the gap check asked> <Its answer, and who gave it.>
3. <A question the gap check asked> <Its answer, and who gave it.>
