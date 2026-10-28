# UndoBudget: irreversibility budget for xv6 process groups

## One-minute overview

This CSL3030 project extends a course-provided xv6-riscv operating system.
The intended end result is a budget shared by processes in the same group:
future kernel operations that spend the budget will use one group balance,
instead of giving every process an independent allowance. This is useful for
demonstrating process inheritance, shared kernel state, system calls, and
concurrency control.

**Current stage:** the kernel can assign a process to a group and configure a
shared group budget. Fork, exec, argument validation, and concurrent
configuration are tested. The kernel does **not yet charge any operation,
refill a balance over time, reject an operation for insufficient budget, or
block waiting for budget**. No project handout is included in this checkout;
the exact operations to charge and any differing handout rules still need to
be confirmed before implementing enforcement.

The repository keeps the upstream xv6 `README` and `LICENSE`. Its Git history
was reset to one project commit; that changes commit attribution, not the
origin or license of the xv6 source.

## Concepts and example

- A **process** is a running xv6 program. Its `gid` is a group number.
- **Fork** creates a child process from a parent. **Exec** replaces the
  program a process runs while keeping that process alive.
- A **group** is one of 16 fixed slots, numbered 0–15. Each slot has one
  shared configuration and one shared `remaining` balance.
- A **budget** has a maximum, a current balance, a refill amount per 100
  ticks, and a mode. These values are stored now; spending and refill are
  future work.
- A **tick** is a timer interrupt counted by the kernel. `ticks` is updated
  in [`kernel/trap.c`](kernel/trap.c).

For example, if a parent joins group 3, calls `setbudget(3, 100, 10,
BUDGET_FAIL)`, and forks, both parent and child point to group slot 3. The
slot starts with `remaining = 100`. The child does not receive a copy of 100.
If the parent later joins group 0, the child stays in group 3. Future charging
would debit group 3's one balance; that debit is not implemented yet.

```mermaid
flowchart LR
    P[Parent process: gid 3] --> G[groups[3]: one shared budget]
    C[Child after fork: gid 3] --> G
    G --> L[Group spinlock protects configuration and balance]
```

## What changed in the kernel

| Area | Current implementation |
| --- | --- |
| [`kernel/param.h`](kernel/param.h) | Defines `NGROUP` as 16. |
| [`kernel/proc.h`](kernel/proc.h), [`kernel/proc.c`](kernel/proc.c) | Adds only `gid` to each process; initializes it to 0, copies it on fork, and clears it when a process slot is reaped. |
| [`kernel/group.c`](kernel/group.c), [`kernel/group.h`](kernel/group.h) | Holds the fixed `groups[NGROUP]` table, one spinlock per slot, configuration functions, and mode constants. |
| [`kernel/main.c`](kernel/main.c) | Initializes all group slots and locks before processes run. |
| [`kernel/syscall.h`](kernel/syscall.h), [`kernel/syscall.c`](kernel/syscall.c), [`kernel/sysproc.c`](kernel/sysproc.c) | Registers syscall numbers 23–25 and their kernel handlers. |
| [`user/user.h`](user/user.h), [`user/usys.pl`](user/usys.pl) | Declares the user functions and generates their `ecall` stubs. |
| [`Makefile`](Makefile), [`user/hello.c`](user/hello.c), [`user/grouptest.c`](user/grouptest.c) | Builds two user programs into `fs.img` for demonstrations and tests. |

The path for a user call such as `setbudget(...)` is:

```text
user program -> usys.pl-generated ecall stub -> syscall.c dispatch
             -> sysproc.c argument handler -> group.c shared state
```

This tree has course-specific interfaces. `argint` returns `void`, so the
handlers read signed `int` values into local variables. Its sleep sequence is
`sleep_prepare(channel)` then `sleep()`; `wakeup(channel)` signals waiting
processes. `copyin` and `copyout` take the process size as an extra argument.
Future budget enforcement must use these actual interfaces.

## Current system calls

| Number | User call | Current behavior |
| --- | --- | --- |
| 23 | `hello(a, b, c, d)` | Returns the sum of four signed integers, or `-1` if the sum is outside signed 32-bit range. `hello(1,2,3,4)` returns `10`. |
| 24 | `setgroup(gid)` | Changes only the calling process's group. Returns `0` for IDs 0–15, otherwise `-1`. |
| 25 | `setbudget(gid, max, refill_per_100_ticks, mode)` | Configures the caller's current group. Returns `0` on success, otherwise `-1`. |

`setbudget` accepts nonnegative signed 32-bit `max` and
`refill_per_100_ticks` values, including zero. Its mode is `BUDGET_FAIL` (0)
or `BUDGET_BLOCK` (1), defined in [`kernel/group.h`](kernel/group.h).
Those modes name the intended future behavior when budget is insufficient;
neither mode currently enforces a limit. A successful call sets `remaining`
to `max`, stores the other settings, records the current tick, and marks the
slot configured. Invalid calls leave the group unchanged. Arguments are
checked before indexing the table or converting signed values to the
64-bit accounting fields.

### Membership and configuration policy

For this teaching stage, any process may join any valid group, and any
**current member** may configure that group. A process cannot configure a
different group without joining it first. This is a simple API rule, not a
security boundary: a process may freely join and reconfigure a group. The
handout must be checked before treating this as the final policy.

### Process lifetime and locking

New process slots begin in group 0. Fork copies the parent's `gid` before the
child can run. Exec keeps the caller's `gid`, whether exec succeeds or fails.
Exit leaves a zombie with its `gid`; reaping clears the process slot. None of
these actions resets the shared group slot. All 16 slots persist until reboot.

Group fields are guarded by that group's spinlock. Configuration takes
`tickslock` first, then the group lock, so the reset and timestamp are
consistent. Future code that reads or updates the shared fields must follow
the same locking rules. Current configuration does no budget arithmetic that
could overflow; later refill calculations will need a cap at `max` and safe
arithmetic.

## Build and demonstrate

Install a RISC-V GCC/binutils toolchain, `qemu-system-riscv64` (version 7.2
or newer), `bc`, and `make`. From the repository root:

```sh
make -j2 kernel/kernel fs.img
make qemu
```

At the xv6 `$` prompt, run:

```text
hello
grouptest
forktest
usertests -q
```

Expected key lines:

```text
hello(1,2,3,4) = 10
hello: PASS
grouptest: PASS (validation, fork, exec, concurrent configuration)
fork test OK
ALL TESTS PASSED
```

Exit QEMU with `Ctrl-a x` (press Ctrl and A, release, then press X). The
default `make` target builds only the kernel; the explicit command above
also creates `fs.img` with `hello` and `grouptest`.

`grouptest` checks invalid IDs and numeric values, valid modes, and the
member-only configuration rule. It uses a pipe so the parent changes groups
before the child proves it inherited the old `gid`. The child checks
membership after a failed exec and after successfully execing `grouptest`.
Four more children repeatedly configure one group to exercise the locking
path. These checks confirm the current API and lifecycle; they do not prove
charging or refill, since those features do not exist yet.

The current checkout was rebuilt and `hello`, `grouptest`, and `forktest`
passed in QEMU with three CPUs. The existing `usertests -q` suite passed
after the configuration changes were added; it was not rerun for this
documentation update. The slow usertests suite has not been run.

## Presentation outline

1. **Problem:** a future irreversible action should spend from one group
   allowance. Independent per-process balances would let a fork duplicate
   that allowance.
2. **Design:** show the diagram and explain why each process stores only a
   `gid`, while `groups[gid]` holds the shared configuration and balance.
3. **Kernel path:** follow `setbudget` from user stub to syscall dispatcher,
   argument handler, validation, and locked group slot.
4. **Lifecycle:** explain group 0 at creation, fork inheritance, exec
   preservation, and persistent group slots after exit.
5. **Demo:** run `hello` and `grouptest`; point out the required sum and the
   fork/exec checks. Mention the passing xv6 quick regression suite.
6. **Next milestone:** agree on handout rules, then implement actual charging,
   100-tick refill, failure or blocking behavior, and tests for those paths.

The precise irreversible operations, their costs, and any different required
mode or authorization semantics cannot be claimed from the current source
tree. They belong to the next handout review and implementation milestone.
