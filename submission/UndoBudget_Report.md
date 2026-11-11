# UndoBudget: Irreversibility Budget for xv6 Process Groups

**CSL3030 project report**  
**Team:** [Add names and roll numbers]  
**Submission date:** [Add date]

## 1. Goal and architecture

UndoBudget limits selected irreversible actions in the course-provided
xv6-riscv tree. Processes in the same group spend from **one shared balance**.
Fork copies a group ID, and exec preserves it; neither action creates a fresh
budget. Group 0 is the trusted administrator. `init` configures group 0 and
default workload group 1 once at boot. The shell stays in group 0 and moves
command children into a configured workload group before redirection or exec.

```text
  init + shell (gid 0) ---- setbudget once ----> groups[0..15]
          |
          +---- fork; child setgroup(gid) ----> workload + descendants
                                                |
                                                | charged syscall
                                                v
  syscall handler / filewrite / exec ---> group_charge(gid, cost)
                                                |
                         per-group lock: refill, check, deduct or wait
                                                |
                         admit effect only after successful charge
```

The `groups[16]` table stores maximum, remaining balance, refill rate, mode,
and counters under one spinlock per group. A process stores only `gid`.
`setbudget` is group-0-only and succeeds once per group; workload membership
is one-way. `budgetstat` returns a locked snapshot to user space.

## 2. Cost policy and enforcement

The group chose a cost policy because the PDF's numbers were examples. One
positive-cost syscall is charged **before its effect**, with no refund after
a later failure. A rejected operation has no intended irreversible effect.

| Operation | Cost |
| --- | ---: |
| `unlink` | 12 |
| Console write, `n > 0` | `2 + ceil(n/128)` |
| Same-group file write, `n > 0` | `2 + ceil(n/1024)` |
| Cross-group file write, `n > 0` | `6 + 2*ceil(n/1024)` |
| `open(O_CREATE)`, `open(O_TRUNC)` | 4, 10; both flags cost 14 |
| `mkdir` / `mknod`, `link`, user `exec` | 6, 3, 4 |
| Other calls | 0 |

The creator group is stored in both disk and memory inodes and survives
reboot. It is initialized when an inode is allocated and cleared on reuse.
This lets `filewrite` distinguish same-group and cross-group writes. The disk
format and `mkfs` were updated together. New images contain 4,000 blocks so
the additional programs leave space for xv6's `writebig` test.

## 3. Concurrency, challenges, and approach

FAIL mode refuses an unaffordable charge. BLOCK mode waits for enough points
from full 100-tick refill periods, then rechecks and deducts atomically. The
charge path takes `tickslock` before the group lock. A waiter registers on
the tick channel before releasing the tick lock, preventing a lost wakeup;
it sleeps with no spinlock held. Filesystem operations that might BLOCK
release inode and log locks before waiting and repeat validation on retry.

Three practical problems shaped the implementation. First, this xv6 uses
`sleep_prepare()`/`sleep()` and size-aware `copyin`/`copyout`, so upstream code
could not be copied directly. Second, a console charge makes very small
workloads unable to print their own failure. A trusted shell `relay` runs the
workload in its selected group, forwards its pipe output, and charges group 0
for console output. Third, the larger user-program image initially caused
`writebig` to run out of blocks; increasing new-image capacity fixed it.

A deterministic Python agent validates six allowlisted requests and sends
them through a framed xv6 helper. File content is sent as bounded hex data,
never as shell text. The bridge requires a matching completion marker and
does not report success from an echo, timeout, or broken connection.

## 4. Verification and limits

On fresh images, the regression suite reported **32 pass, 0 fail, 0 untested**
across one and three CPUs. It covers authorization, fork/exec sharing, exact
costs, refusal with surviving files, refill and BLOCK races, inode persistence,
and agent responses. Ten repeatable experiments produced raw serial logs,
CSV observations, and four plots. Full xv6 `usertests` and crash recovery
also passed in a disposable copy. The 26-command demo sequence passed.

xv6 has no user identities or file permissions, so the group-0 shell and its
binary are trusted. A failure after an admitted truncate or partial write
can leave an incomplete file; the charge is retained by policy. Group slots
are configured once per boot. These are project limits, not guarantees of
general-purpose OS isolation.
