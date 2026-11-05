# UndoBudget — Credit-Efficient Astra Prompt Pack

**Source:** Split and strengthened from the supplied `MASTER IMPLEMENTATION PROMPT` for *UndoBudget — Irreversibility Budgets for Process Groups in xv6*.

## How to use
1. Create a feature branch and checkpoint your current work **yourself**. Put the companion `AGENTS_UndoBudget.md` contents at repository root as `AGENTS.md` (review and commit it yourself), or paste its contents once into Astra's session instructions if repository access is unavailable.
2. Send **one** numbered prompt at a time. All prompts presume Astra can inspect the repo and will read `AGENTS.md`. Keep the same task thread until it passes; start a fresh task context at phase boundaries if previous history gets too long.
3. After each code-writing prompt, inspect the diff, build, run focused tests, and commit/push **manually**. Read-only design prompts need no code commit unless you save a review document.
4. Do not use the illustrative costs as final policy unless the official lab assignment explicitly confirms them. If the handout is not in the repo, supply it before P01.
5. An unrun test is *not a pass*. Astra should never hide lack of QEMU/terminal access.

## User's manual Git routine

Do once before the first code change (after checking `git status`):

```bash
git switch -c feat/undobudget-phased
# If working-tree changes exist, inspect and save a deliberate baseline checkpoint.
# Never blindly stage generated binaries, fs.img, secrets, or unrelated files.
```

After each **successful** implementation task:

```bash
git status --short
git diff --check
git diff
# Stage only the files you reviewed:
git add -p                 # for tracked changes
git add path/to/new-file    # if the task adds a new file
git diff --cached --check
git diff --cached
git commit -m "<recommended message from prompt>"
git push                  # after first `git push -u origin feat/undobudget-phased`
```

If build/tests fail, **do not commit**; reuse the same task context with the smallest reproduction and relevant error output. Do not paste the entire master prompt again.

---

## Phase 0 — Understand and protect existing code

### P00 — Repository audit and baseline (READ ONLY)

> Read `AGENTS.md`. **Do not modify code or Git.** Inspect `kernel/group.c`, `group.h`, `proc.c`, `proc.h`, `main.c`, `syscall.c`, `syscall.h`, `sysproc.c`, `param.h`, `trap.c`, `defs.h`, `user/user.h`, `user/usys.pl`, `Makefile`, and `user/grouptest.c`. Map the actual `setgroup`, `setbudget`, fork/exec inheritance, locks, and sleeping/ticks interfaces. Confirm or correct the claimed current state and syscall IDs 23–25. Check `git status`, compile with `make -j2`, and where QEMU is available boot and run `hello`, `grouptest`, `forktest`, `usertests -q`. Do not assume a timeout is a pass. Return a brief implementation map, actual results, existing defects, and a minimal file-change plan. **Stop after audit; do not implement anything.**

**Gate:** User has reviewed the audit, saved a checkpoint/branch, and understands baseline failures. **Commit:** Optional `docs: record UndoBudget baseline audit` only if you manually save the findings.

---

## Phase 1 — Fail-safe charging of shared budgets

### P01 — Confirm cost policy and charging semantics (READ ONLY)

> Read `AGENTS.md` and the official team-specific lab handout (ask me for it if missing). **Do not edit code.** Extract the **exact** assigned operation costs, including console/file writes, same-group/cross-group writes, unlink, and exec if applicable. Clarify whether failed/invalid syscalls are charged, which calls are exempt, and whether a charge is per call or per byte. Compare these requirements with existing syscall paths. Propose a minimal charging API and **specific enforcement points**; for ownership-sensitive operations inspect how the inode can be acquired before effect without unsafe lock ordering. Identify any ambiguity requiring my choice. Finish with an exact short policy table and a STOP; do not invent missing values.

**Gate:** Confirmed cost table and explicit design decisions. **Commit:** NO COMMIT.

### P02 — Core atomic charge in FAIL mode (IMPLEMENT)

> Read `AGENTS.md`, the agreed P01 cost policy, `kernel/group.c/.h`, `kernel/defs.h` and related group code. **Implement only** an atomic, lock-protected shared-budget charge operation for FAIL mode; no syscall hooking, inode changes, refill, or BLOCK mode yet. Define a small reusable interface matching this xv6 tree, validate gid/cost, reject insufficient funds before deduction, forbid negative balances/overflow/double spending, and preserve current setbudget behavior. If zero-cost handling or unconfigured-group behavior is unspecified, stop and ask before changing it. Add the smallest possible focused tests if feasible. Run build and report results, modified files, risks, and the commit message `feat(budget): add atomic fail-mode charging`. Stop.

**Gate:** API correct under contention; build green, zero/exhaustion/invalid tests. **Commit:** Above after review.

### P03 — Hook up one syscall: unlink (IMPLEMENT)

> Read `AGENTS.md`, the confirmed cost table and P02 implementation. **Implement budget enforcement for `unlink` only.** Inspect the actual `sys_unlink` and dispatch path and place the charge so a refusal cannot delete a file; avoid filesystem lock-order violations. Do not implement write/exec ownership costs here. Ensure unrelated syscalls, shell behavior and configured/unconfigured-group behavior remain consistent with the agreed policy. Build and provide a minimal xv6 test showing a permitted unlink and a refused unlink whose file survives. If the exact charging moment for invalid/unlink failures is unspecified, present the tradeoff and stop for a decision. Recommend commit `feat(budget): enforce unlink budget before deletion`. Stop.

**Gate:** Both accepted and refused cases proven; existing tests unaffected.

### P04 — FAIL mode regression and concurrency tests (TEST ONLY)

> Read `AGENTS.md`. **Do not change production kernel code unless I explicitly approve a diagnosed bug fix.** Add repeatable xv6 user tests for (a) 50-unit budget with unlink cost 10 and no refill **only if confirmed by P01**, creating files before invoking deletions; (b) parent and child sharing the same group budget; (c) two independent groups; (d) concurrent deletion attempts that cannot overspend; (e) invalid gid/cost. Verify no rejected deletion takes effect. Build and run tests on `CPUS=1` and `CPUS=3` if available; report precise results and test locations. Recommend `test(budget): cover fail-mode accounting and concurrency`. Stop.

**Gate:** No overspend/no unintended deletion; existing group tests pass.

---

## Phase 2 — Persistent file creator-group information

### P05 — Disk inode layout review (READ ONLY)

> Read `AGENTS.md`; **no code changes**. Inspect `kernel/fs.h`, `fs.c`, `file.c`, `sysfile.c`, `mkfs/mkfs.c` and inode block constants. Determine on-disk and in-memory inode sizes, IPB impact of an added creator gid, alignment, size assertions, inode allocation/reuse/load/update paths, and how `fs.img` is built. Identify exactly which files and initialization points need changes. Explain how to rebuild the image without destroying irreplaceable data. Stop with a precise, minimal migration plan; do not edit until I approve.

**Gate:** Disk format and mkfs alignment understood. **Commit:** NO COMMIT.

### P06 — Add persistent creator gid, nothing else (IMPLEMENT)

> Read `AGENTS.md` and P05 findings. **Implement only** a creator-group field in the disk inode and matching in-memory inode. Initialize it at creation using the creating process's gid; load/persist it correctly, clear stale data on inode reuse, update mkfs consistently, and add a narrow test verifying persistence and delete/recreate behavior. Do **not** add any ownership-dependent charging yet. Rebuild `fs.img` if the disk format changed using the actual Makefile commands; run filesystem smoke tests. Report inode layout before/after, test evidence and commit `feat(fs): persist inode creator group`. Stop.

**Gate:** Kernel/mkfs formats agree; no stale metadata; filesystem tests pass.

### P07 — Group-sensitive file-write costs (IMPLEMENT)

> Read `AGENTS.md`, the P01 official cost table and persistent creator gid implementation. **Implement only file-write charging**, distinguishing same-group and cross-group cases exactly as specified. Inspect descriptor/inode lookup and existing `write`/`filewrite` path; place the charge before irreversible write effects, without accessing user pointers unsafely or creating filesystem/group lock inversions. Address console writes separately **only if** required by the confirmed table, and do not change exec. Add tests for same-group, cross-group, budget refusal with unchanged contents, and malformed fd. Run focused regression tests. Recommend `feat(budget): enforce ownership-aware writes`. Stop.

**Gate:** Correct costs, refused write has no effects, no deadlock.

### P08 — Group-sensitive exec costs (IMPLEMENT, IF REQUIRED)

> Read `AGENTS.md` and the confirmed assignment. **If and only if** exec charging is required, implement ownership-sensitive exec accounting. Inspect how xv6 opens/validates the executable inode and when process image replacement becomes irreversible. Charge safely **before commit**, without using an unvalidated user pointer or holding an unsafe lock across possible blocking. Preserve gid across successful exec and verify refusal does not replace the caller image. Add same-group/cross-group/insufficient-budget tests and compile. If exec cost is not required, report `SKIPPED — not in handout` and edit nothing. Recommend `feat(budget): enforce creator-aware exec costs`. Stop.

**Gate:** No charge after successful side effects; exec and shell regressions pass.

---

## Phase 3 — Lazy refill

### P09 — Implement lazy refill safely (IMPLEMENT)

> Read `AGENTS.md`, the actual `ticks`/`tickslock` interfaces and group locking. **Implement lazy refill only** in the charging path, using full elapsed 100-tick periods, preserving remainder in `last_refill`, clamping to max, avoiding multiplication/addition overflow and unsafe lock-order nesting. Confirm how `setbudget` initializes or resets `last_refill`. Keep FAIL semantics; do **not** add sleeping/BLOCK mode. Write a small test or trace for precise boundary cases and run build. Recommend `feat(budget): add bounded lazy tick refill`. Stop.

**Gate:** Refill at multiples of 100 ticks, no drift, max respected.

### P10 — Refill edge and race tests (TEST ONLY)

> Read `AGENTS.md`; add focused tests, with no production edits without approval, for 99 vs 100 ticks, multiple periods, max saturation, partial-period retention, reconfiguration, high numeric values, tick wraparound assumptions and concurrent charges on `CPUS=3`. Avoid timing-flaky equality assertions; account for elapsed ticks deterministically or use bounded observation. Run and report precise pass/fail evidence. Recommend `test(budget): cover refill boundaries and races`. Stop.

**Gate:** Tests are deterministic enough to reproduce; no overflow or cap failures.

---

## Phase 4 — BLOCK mode, sleep and wakeup

### P11 — Prove BLOCK-mode sleep/wakeup design (READ ONLY)

> Read `AGENTS.md`. Inspect this repository's `sleep_prepare`, `sleep`, `wakeup`, scheduler, `clockintr`/tick wakeups and process-kill behavior. **Do not write code.** Propose a lock/wait-channel protocol for BLOCK-mode charging which guarantees no lost wakeups or sleeping with a spinlock, and rechecks balance after every wake. Explain how changes in setbudget/refill wake sleepers; how zero-refill groups, costs above max, spurious wakeups, and killed callers behave. Provide pseudocode and lock ordering for review. Stop until I approve.

**Gate:** User approves a sound wait/wakeup and cancellation design. **Commit:** NO COMMIT.

### P12 — Implement BLOCK mode only (IMPLEMENT)

> Read `AGENTS.md` and approved P11 design. Implement **only** BLOCK behavior in the existing charge path, preserving FAIL behavior. Use the actual xv6 sleep interfaces. Never hold spinlocks across sleeping; make sleep and condition checks race-safe. On wake, recompute refill, recheck affordability, and deduct atomically; handle kills and reconfiguration as designed. Do not add budgetstat or agent features. Build, run one focused block-until-refill test, and explain exact changes. Recommend `feat(budget): add race-safe block and wakeup`. Stop.

**Gate:** Blocks without polling, wakes properly, does not overspend.

### P13 — BLOCK mode stress/regression tests (TEST ONLY)

> Read `AGENTS.md`. Add tests for exhaustion then refill/wakeup, multiple group members contending for refilled points, wakeup with insufficient funds, zero refill, killed waiter, and `setbudget` reconfiguration. Run on one and three CPUs, including simultaneous operation by independent groups. Assert no hangs except intentionally waiting cases, using bounded termination where possible. Do not alter production code without my review; report minimal reproductions for failures. Recommend `test(budget): stress block-mode wakeups`. Stop.

**Gate:** Race tests and existing xv6 usertests pass.

---

## Phase 5 — Kernel statistics and xv6 UI

### P14 — Statistics snapshot syscall (IMPLEMENT)

> Read `AGENTS.md`; implement **only** a read-only kernel snapshot syscall for group budgets using proper locking, bounds checks, argument copying and the correct `copyout()` API. Include gid, configured, remaining, max, refill, mode, and n_allowed/n_blocked/n_refused with explicit counter semantics (attempts vs calls vs sleep episodes). Choose a free syscall number after inspecting current allocations; correctly register through headers/dispatch/usys and add a shared user-visible struct. Avoid exposing kernel pointers. Add invalid-buffer and concurrency tests; build. Recommend `feat(budget): expose safe budget snapshots`. Stop.

**Gate:** Snapshot consistent and safe under concurrent changes.

### P15 — `budgetstat` shell tool (IMPLEMENT)

> Read `AGENTS.md` and the finished snapshot API. Add **only** `user/budgetstat.c` and necessary Makefile entry; format the group table clearly without assuming a host libc. Test unconfigured groups, active groups, and changing counters. Avoid unnecessary kernel changes. Run in xv6 if available; otherwise explicitly state tests not run. Recommend `feat(user): add budgetstat command`. Stop.

**Gate:** Output agrees with manually computed budget and counters.

---

## Phase 6 — Deterministic host-side Python agent

### P16 — Structured tool schema + validator (HOST ONLY)

> Read `AGENTS.md`. **Do not edit the kernel.** Implement a small Python package for deterministic requests with a fixed allowlist: `list_files`, `read_file`, `delete_file`, `write_file`, `execute_program`, `get_budget_status`. Validate JSON shape and types, required arguments, bounded file content/paths, and path traversal including relative/absolute/`..` edge cases. Do not execute arbitrary shell strings. Return structured validation errors. Add Python unit tests and run them. No QEMU integration yet. Recommend `feat(agent): validate deterministic tool requests`. Stop.

**Gate:** Invalid and malicious tool requests are rejected in host tests.

### P17 — xv6 guest-side command helper (GUEST ONLY)

> Read `AGENTS.md` and the agreed tool protocol. Implement the **smallest safe xv6 user-space helper** to perform one validated file operation and return unambiguous machine-readable success/failure, including budget-refusal reporting where observable. Start with `list_files` and `read_file`; add mutation tools only after the first two pass. Do not modify kernel charging or Python transport yet. Avoid injection via arbitrary shell command construction. Add helper to Makefile, test manually in xv6 and recommend `feat(agent): add controlled xv6 operation helper`. Stop.

**Gate:** Clear command completion and error indicators; no unchecked shell execution.

### P18 — QEMU serial bridge (HOST ONLY)

> Read `AGENTS.md` and inspect actual Makefile/QEMU serial settings. Implement **only** a Python bridge to communicate with the running xv6 helper and return structured outputs: request ID, stdout, status, error, elapsed time. Use a unique completion marker/framing protocol that cannot be mistaken for an echoed command; handle startup, concurrency/serialization, timeouts, broken pipe and unexpected QEMU exits. Do not add an LLM or alter kernel. Unit-test parser/timeout logic using fake streams, then test one `list_files` roundtrip if available. Recommend `feat(agent): add reliable QEMU serial bridge`. Stop.

**Gate:** Success proven by actual guest response, not host write success.

### P19 — Deterministic agent orchestration (HOST ONLY)

> Read `AGENTS.md`. Integrate existing Python validation and bridge with a minimal deterministic request executor (no LLM). Implement supported tool dispatch and structured results, including budget status parsing; add tests with mocked bridge and guest smoke tests for each tool. Every operation must return only verified guest status. Do not bypass the kernel's budget controls or fabricate success from console text. Recommend `feat(agent): orchestrate validated xv6 tools`. Stop.

**Gate:** End-to-end validation -> bridge -> xv6 -> response works.

---

## Phase 7 — Demonstrate kernel budget control over agent actions

### P20 — Agent-to-budget integration scenarios (TEST + FIX ONLY IF APPROVED)

> Read `AGENTS.md`. Add repeatable tests of agent successful deletion, FAIL exhaustion, BLOCK waiting and subsequent success, fork inheritance, and independent groups. For each request capture original JSON, validated arguments, guest operation, kernel result, remaining budget, elapsed time and agent-visible result. Use the **official** confirmed cost table; do not hardcode example costs unless they match. Keep kernel edits out of scope unless a concrete failure is found and I approve a targeted fix. Recommend `test(agent): verify kernel-enforced budgets end to end`. Stop.

**Gate:** An agent cannot make an unaffordable irreversible call succeed.

---

## Phase 8 — Optional LLM integration

### P21 — Add an LLM planner (OPTIONAL)

> Read `AGENTS.md`. Only if P19–P20 are fully green, introduce an optional LLM planner producing **structured allowlisted tool calls** for the existing deterministic validator and bridge. Keep deterministic mode as default for regression testing. Never accept arbitrary generated shell commands or treat model assertions as execution results. Add tests for malformed calls, repeatedly requested deletion and budget refusal. Do not expose unneeded credentials or expand available tools. Recommend `feat(agent): add optional bounded llm planner`. Stop.

**Gate:** Disabling LLM retains all deterministic functionality.

---

## Phase 9 — Full regression / concurrency

### P22 — Comprehensive hardened test suite

> Read `AGENTS.md`. Aggregate and run the existing and new tests: budget initialization and invalid arguments, gid fork/exec behavior, atomic shared accounting, FAIL and BLOCK modes, exact refill boundaries, inode creator persistence and reuse, write/exec ownership costs if assigned, agent invalid requests and bridge timeouts. Test `CPUS=1` and `CPUS=3`; include blocked waiters while refilling and independent groups. Do **not** refactor product code. Report pass/fail/untested in a compact matrix with commands and failure reproductions. Recommend `test: consolidate UndoBudget regression coverage`. Stop.

**Gate:** All required tests run and pass; remaining failure/untested documented.

---

## Phase 10 — Evaluation and graphs

### P23 — Reproducible experiment harness

> Read `AGENTS.md`. Implement only repeatable experiments with raw logs and CSV outputs for FAIL deletion plateau, BLOCK refill staircase, shared fork spending, concurrency on one vs multiple CPUs, and independent groups. Build a separate Python plotting script that reads actual CSV data and saves figures for completed deletions vs time, remaining budget, counter breakdown, and FAIL/BLOCK comparison. Never invent measurements; label missing experiments explicitly. Keep plotting and data collection separate from kernel behavior. Recommend `experiment: add reproducible UndoBudget evaluation`. Stop.

**Gate:** Each plotted number is traceable to a real execution record.

---

## Phase 11 — Documentation and demo

### P24 — README, design journal, demo/viva

> Read `AGENTS.md` and the current repository/tests. Update README and docs **only** to explain the actual architecture, syscall flow, chosen cost table, creator-gid inode format, FAIL/BLOCK, lock order, refill, budgetstat, deterministic agent, test commands, evidence, limitations and expected demo. Draft a short demo script for boot -> group config -> inherited sharing -> FAIL -> BLOCK/refill -> budgetstat -> agent rejection -> two independent groups. Add design journal and viva questions based on implemented code; do not claim untested features work. Recommend `docs: finalize UndoBudget design and demonstration`. Stop.

**Gate:** Every demonstration command works in this exact repository.

---

## Cheap debugging prompts (instead of rerunning the whole master request)

### D1 — Fix compilation only

> Read `AGENTS.md`. We are still on task **Pxx**. Here is the **first** compiler error and recent diff: [paste]. Diagnose the root cause; inspect only relevant files, make the smallest safe patch, rerun `make -j2`, and report exact changed lines. Do not implement other tasks or do unrelated cleanups. Do not commit. Stop after build result.

### D2 — Fix one failing runtime test

> Read `AGENTS.md`. We are still on task **Pxx**. Reproduction: [commands], expected: [expected], actual: [output]. Trace the relevant kernel/user path and explain why it fails. Propose one narrow fix, implement only that fix, run the failing case plus closely related regressions, and report results. Do not move to the next task or commit.

### D3 — Review before my manual commit (READ ONLY)

> Read `AGENTS.md`. Review **only the unstaged/staged diff for Pxx** for correctness, syscall-registration mistakes, lock-order issues, lost wakeups, overflow, user-pointer misuse, on-disk inode mismatch and missing tests as relevant. Do not change anything. Give: blockers, precise test commands, a concise summary, and whether the diff is ready for me to commit. No commit/push.

## Rules for cheaper iterations

- Do Phase 0/P01/P05/P11 as **read-only design** steps; never pay for full codegen before resolving assumptions.
- Supply Astra with its last summary and the **exact failing error**, not the 1,071-line master prompt repeatedly.
- Use the same narrow task after a failed test. Keep generated code out of unrelated files.
- Each task should modify approximately 1–3 related files, except necessary syscall registration/mkfs consistency changes.
- Use `make -j2` for routine builds; use `make clean` / fresh `fs.img` specifically after filesystem layout changes or when stale build artifacts are suspected.
- Start each implementation from a passing manual Git commit, so `git diff` stays focused and rollback is straightforward.
- Do not expect a formal guarantee of zero bugs. The objective is small changes with verifiable evidence and safe rollback.
