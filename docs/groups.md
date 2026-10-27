# Shared group budget foundation

The handout was not available during implementation. These are explicit
teaching-project choices to reconcile with it when supplied.

## State and lifecycle

`NGROUP` is 16 (`kernel/param.h`), with valid IDs 0 through 15. Each fixed
slot in `kernel/group.c` has its own spinlock and holds the shared maximum,
remaining budget, refill amount, refill timestamp, mode, and configured flag.
Only `gid` is added to `struct proc`; a fork never copies a budget.

All slots and locks are initialized before the first process runs. Groups start
unconfigured with zeroed accounting fields. A new process slot defaults to group
0. Fork copies the parent's `gid` before the child becomes runnable. Exec keeps
the process's existing membership, including when exec fails.

Exit performs normal file cleanup with the original membership. The zombie
retains its `gid` until reaped, when `freeproc` clears it for reuse. Exiting or
switching groups never resets shared budgets. There is no group allocation,
deletion, or membership reference count: all slots persist until reboot.

`gid` is private to the running process; fork initializes the child while holding
the child's process lock. Shared group fields require the corresponding group
lock after boot. No budget charging, timer refill, or blocking is active yet.

## Configuration API and policy

User programs include `kernel/types.h`, `user/user.h`, `kernel/param.h` for
`NGROUP`, and `kernel/group.h` for mode constants.

| Call | Result and effect |
| --- | --- |
| `setgroup(gid)` | Join group `gid`; return 0 on success, -1 for an invalid ID. Only the caller changes membership. |
| `setbudget(gid, max, refill_per_100_ticks, mode)` | Configure the caller's current group; return 0 on success, -1 on invalid arguments or nonmembership. |

This teaching kernel has no user identities or administrators. Any process may
join any valid group, and every member may reconfigure its group. A caller must
join before configuring another group. This policy provides no isolation from
untrusted processes, which can join and change budgets themselves.

Both numeric budget arguments are signed 32-bit integers in the range
0 through 2147483647. Zero maximum is a valid empty allowance; zero refill means
no replenishment. Refill may exceed maximum; future refill logic must cap the
balance at maximum. Valid modes are `BUDGET_FAIL` (0, intended to reject an
operation without sufficient budget) and `BUDGET_BLOCK` (1, intended to wait).
Their enforcement is deferred; configuration itself never waits for budget.

Every successful configuration resets the shared remaining balance to `max`,
stores the refill amount and mode, records current `ticks` as `last_refill`, and
marks the slot configured. Invalid calls leave state unchanged. Configuration
does not alter any process's membership.

Validation happens before table indexing or unsigned conversion. Accounting
fields use `uint64`; this milestone performs no budget addition or
multiplication. The timestamp uses the same unsigned type as `ticks`. The lock
order is `tickslock` then the selected group's lock, released in reverse order;
no process lock is held on this path. The entire configuration changes under one
group lock, so future readers must take that lock to obtain a consistent view.

## Verification

Build with `make -j2 kernel/kernel fs.img`, then run `make qemu`. The existing
`forktest` exercises process-table exhaustion, exit, and reaping. Run these
commands inside xv6:

```text
hello
grouptest
forktest
usertests -q
```

`hello` checks the required sum and signed overflow handling. `grouptest` checks
ID and numeric boundaries, modes, membership restrictions, and inherited
membership across fork and exec. A pipe makes the parent change groups before
the child checks its membership. It also tests failed exec and several children
configuring one group concurrently. Inheritance is observed through the
member-only configuration rule, without adding another syscall. These tests
cover the foundation; balance charging and refill tests belong with their later
implementation.

Verified with the default three QEMU CPUs: the kernel and filesystem image
built successfully, `hello(1,2,3,4)` returned 10, `grouptest` printed PASS,
`forktest` printed `fork test OK`, and `usertests -q` finished with
`ALL TESTS PASSED`. The last command runs the existing quick suite; the slow
suite has not been run for this milestone.
