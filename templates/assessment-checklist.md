**Week one: assessing a harness someone else built**

*Look (days one and two)*
- [ ] Inventory: what exists for each of the eight parts (chapter 4), and what doesn't.
- [ ] Setup from a fresh clone, as documented: how long, and which steps failed.
- [ ] Every check, locally and in CI: how long, and whether it passes on the main branch.
- [ ] Instruction files: what the agent loads, how big, and which claims are still true.
- [ ] Silent gates: hooks that can't block, checks that read nothing, jobs CI skips.
- [ ] Each strange guard: why it exists, found before anything is removed.

*Measure (days three and four)*
- [ ] Rework by folder from the git history, with bookkeeping files left out.
- [ ] CI failures by check and by branch.
- [ ] Where developers redo agent work, and what they've stopped asking it to do.
- [ ] Cost per task (tokens, dollars and turns), if the platform records it (chapter 2).

*Rank (day four)*
- [ ] For each failure: how often, what one costs, and the product.
- [ ] The top three, each with where it's caught today and where it could be caught earlier.

*Change (day five)*
- [ ] One change: the cheapest guard for the top failure.
- [ ] The same measurement, repeated after the change lands.
- [ ] What you chose not to change, and why.
