# The changelog convention

<!-- Ship. How this kit's projects keep CHANGELOG.md. The lab's own CHANGELOG.md is the filled
example, and node tools/kit.mjs changelog CHANGELOG.md checks the parts a script can. -->

A changelog is the record a person reads to learn what changed, why, and how it was checked, without reading every commit. It's written with the change, not after it.

## What a script checks

- The file starts with `# Changelog`.
- Each entry is a heading, `## YYYY-MM-DD, what changed`, newest first. Two entries may share a day.
- Each entry has at least one bullet, a line starting `- `.

## What a person checks

- **Same commit.** The entry is in the commit that makes the change, so the record and the code can't drift apart.
- **What and why.** Each bullet says what changed, where (the file or command), and why: the problem, the ticket or the decision behind it.
- **How it was checked.** Name the command and what it showed, such as the number of checks that passed, and say what wasn't run.
- **Numbers as they were.** An entry records what was true that day. When a later change makes it wrong, the later entry says so; the old one isn't rewritten.
- **Plain words.** Written for someone who wasn't there: no shorthand only the author knows.
