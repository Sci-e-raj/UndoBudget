# CSL3030: Irreversibility budget for process groups

## Goal and baseline

Extend this course-provided xv6-riscv tree to track and enforce an irreversibility
budget for process groups, using the project handout for the exact API and policy.
Keep the original `README` and adapt changes to this tree's interfaces.

Baseline checked on branch `riscv` at `f780d78`: the working tree was clean,
`make -B -j2 kernel/kernel fs.img` succeeded, and `make qemu` booted to the xv6
shell. No project handout is stored in this repository; confirm its exact
requirements before implementing the budget behavior.

## Build and run

From the repository root, with a RISC-V GCC/binutils toolchain, QEMU for
RISC-V, and `bc` on `PATH`:

```sh
make -j2 kernel/kernel fs.img
make qemu
```

At the xv6 shell, run the desired user program or test. Exit QEMU with
`Ctrl-a x`. Use `make clean` to remove generated build files before a fresh
build. The default `make` target builds only `kernel/kernel`; the command above
also builds `fs.img`.

## Tree-specific notes

- `kernel/syscall.h` assigns 1 through 25: `hello` is 23, `setgroup` is 24,
  and `setbudget` is 25. The next unused number is 26.
- `sleep_prepare(void *chan)` registers a channel, then `sleep(void)` blocks;
  `wakeup(void *chan)` signals sleepers. This is not the two-argument sleep API.
- `ticks` and `tickslock` are declared in `kernel/defs.h` and defined in
  `kernel/trap.c`; `clockintr()` increments ticks and wakes sleepers on `&ticks`.
- `copyin(pagetable_t, uint64 size, char *dst, uint64 src, uint64 len)` and
  `copyout(pagetable_t, uint64 size, uint64 dst, char *src, uint64 len)` include
  a process-size argument. `argint` and `argaddr` return `void`.
- New syscalls will need matching entries in `kernel/syscall.h`,
  `kernel/syscall.c`, `user/user.h`, and `user/usys.pl`.

## Three-week milestones

- Week 1: document and verify the baseline; map the process, timer, syscall,
  and filesystem paths; define the budget API and invariants from the handout.
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
- [ ] Confirm exact API and policy against the project handout.
- [x] Add shared group state and fork inheritance; document exec and exit in
  [groups.md](groups.md).
- [x] Add `setgroup` and `setbudget`, user stubs, validation, and a documented
  member-only configuration policy.
- [x] Add `grouptest` for argument validation, fork/exec membership, and
  concurrent configuration.
- [x] Build and run `hello`, `grouptest`, `forktest`, and `usertests -q` after
  configuration changes; all passed with the default three QEMU CPUs.
- [ ] Implement budget charging, refill, and mode enforcement in later work.
