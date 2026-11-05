# UndoBudget: instructions for coding agents

Project: CSL3030 xv6-riscv UndoBudget. This repository already contains partially working code. Work **only** on the user-requested numbered microtask. Do not implement future tasks.

## Nonnegotiable workflow
- Read the relevant existing implementation and `kernel/defs.h` before editing. Verify actual xv6 interfaces instead of assuming upstream xv6 behavior.
- Preserve working code, public behavior, syscall IDs (currently `hello=23`, `setgroup=24`, `setbudget=25`, subject to audit), and existing tests. No unrelated refactors or new dependencies.
- Keep changes focused and minimal; avoid broad formatting churn. List files to be changed before editing. If the requested task depends on missing handout details, repository files, or an unresolved design choice, **stop and ask** rather than inventing behavior.
- `unlink=10`, console-write=1, cross-group-write=3, and cross-group-exec=5 are **illustrative examples only** until verified against the team's official assignment.
- Kernel enforcement must occur before irreversible effects; validate gid, size and user arguments. Never directly dereference user pointers. Ensure rejected calls cannot perform the operation. Investigate the correct charging site per syscall; generic dispatch is not always suitable for inode-dependent costs.
- Use spinlocks, inode locks, and logging as implemented in this repository. No sleeping with a held spinlock. For BLOCK mode, prove wakeups cannot be lost; check conditions in a loop. Inspect whether `sleep_prepare()` actually exists and how it is intended to be used.
- Keep timer reads and lock ordering safe. Protect arithmetic against overflow; enforce `0 <= remaining <= max`. Handle impossible-to-satisfy costs, zero refill, and killed processes deliberately.
- If disk inode layout changes, update kernel and mkfs representations consistently and rebuild `fs.img`; do not assume old images remain valid.
- Tests must include negative/invalid cases, regression, and concurrency when relevant. Use `make -j2` after code changes; run focused QEMU tests and `usertests -q` at appropriate checkpoints. Report failures; do not say tests passed unless actually run.
- **Never run `git add`, `git commit`, `git push`, reset, checkout, rebase, or destructive cleanup. The user manages Git.** Do not edit or delete user files outside task scope.

## Required final response for each microtask
1. What was found and whether assumptions match the repository.
2. Exact changed files and concise design rationale.
3. Build/tests run, command and result; clearly state anything not run.
4. Risks, corner cases, and any decision requiring user input.
5. Recommended single commit message, or `NO COMMIT` if read-only/unfinished.
6. Explicitly say `STOP — task complete` or `STOP — blocked`. Do not start the next microtask.

Prefer small diffs, concise explanations, and no repeated project-wide summaries. Do not claim error-free code; demonstrate correctness with evidence.
