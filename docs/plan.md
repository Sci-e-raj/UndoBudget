# CSL3030: Irreversibility budget for process groups

## Goal and baseline

Extend this course-provided xv6-riscv tree to track and enforce an
irreversibility budget for process groups. The reference project PDF supplies
the problem statement; the team chose the approved engineering cost table in
[`design.md`](design.md). Keep the original `README` and use this tree's
actual interfaces.

Baseline checked on branch `riscv` at `f780d78`: the working tree was clean,
`make -B -j2 kernel/kernel fs.img` succeeded, and `make qemu` booted to the xv6
shell. This is a historical baseline record, not the current implementation
status.

## Build and run

From the repository root, with a RISC-V GCC/binutils toolchain, QEMU for
RISC-V, and `bc` on `PATH`:

```sh
make -j2 kernel/kernel fs.img
make qemu
```

At the xv6 shell, run the desired user program or test. Exit QEMU with
`Ctrl-a x`. The default `make` target builds only `kernel/kernel`; the command
above also builds `fs.img`. For repeatable tests, prefer the scratch-image
harnesses in `tests/` and `experiments/`. Back up any irreplaceable `fs.img`
before a forced image rebuild; the creator-gid inode layout requires the
matching `mkfs` image format.

## Tree-specific notes

- `kernel/syscall.h` assigns 1 through 26: `hello` is 23, `setgroup` is 24,
  `setbudget` is 25, and `budgetstat` is 26.
- `sleep_prepare(void *chan)` registers a channel, then `sleep(void)` blocks;
  `wakeup(void *chan)` signals sleepers. This is not the two-argument sleep API.
- `ticks` and `tickslock` are declared in `kernel/defs.h` and defined in
  `kernel/trap.c`; `clockintr()` increments ticks and wakes sleepers on `&ticks`.
- `copyin(pagetable_t, uint64 size, char *dst, uint64 src, uint64 len)` and
  `copyout(pagetable_t, uint64 size, uint64 dst, char *src, uint64 len)` include
  a process-size argument. `argint` and `argaddr` return `void`.
- The current project syscalls have matching entries in `kernel/syscall.h`,
  `kernel/syscall.c`, `user/user.h`, and `user/usys.pl`.

## Three-week milestones

- Week 1: document and verify the baseline; map process, timer, syscall, and
  filesystem paths; define the shared budget API and invariants.
- Week 2: implement group accounting and enforcement at the required kernel
  paths, with user-facing syscall plumbing and focused tests.
- Week 3: test group lifecycle and boundary cases, run the existing xv6 tests,
  fix regressions, and document final behavior and limitations.

## Checklist

- [x] Inspect this tree's relevant interfaces and build rules.
- [x] Rebuild kernel and filesystem image; boot to the xv6 shell.
- [x] Document the baseline and plan.
- [x] Add `hello(int, int, int, int)` and its user test. It returns the sum,
  or -1 if the sum does not fit in a signed 32-bit integer. Run `hello` at
  the xv6 shell; the required result is `hello(1,2,3,4) = 10` and `hello: PASS`.
- [x] Separate illustrative reference costs from the approved project policy.
- [x] Add shared group state and fork inheritance; document exec and exit in
  [groups.md](groups.md).
- [x] Add `setgroup` and `setbudget`, user stubs, validation, group-0-only
  one-time configuration, and one-way workload membership.
- [x] Add `grouptest` for workload argument validation and fork/exec
  membership; add `groupauth` workload checks. Its administrator-only mode
  contains a concurrent first-configuration test and runs in the disposable
  `tests/admin_boot.py` trusted boot harness.
- [x] Build and run `hello`, `grouptest`, `forktest`, and `usertests -q` after
  configuration changes; all passed with the default three QEMU CPUs.
- [x] Add group-locked atomic charging, bounded 100-tick lazy refill, FAIL and
  BLOCK behavior, and read-only `budgetstat` snapshots.
- [x] Persist creator gid in disk and memory inodes; rebuild images with the
  new magic and `mkfs` layout.
- [x] Enforce approved unlink and creator-aware regular-file write costs.
- [x] Enforce create, truncate, mkdir, mknod, and link costs before filesystem
  transactions, with exact-cost and refusal-survival tests.
- [x] Add the deterministic Python validator, serial bridge, xv6 helper,
  executor, and focused regression and evaluation scripts.
- [x] Enforce approved console and flat user-exec costs; support all six
  deterministic agent tools end to end with framed guest results.
- [x] Increase new-image capacity to 4000 blocks so the bundled programs
  leave room for `usertests`' `writebig` case; preserve existing `fs.img`.
