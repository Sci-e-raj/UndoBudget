# UndoBudget groups and authorization

## Implemented foundation

There are 16 fixed groups (`gid` 0 through 15). Each slot in `kernel/group.c`
holds one shared budget configuration and has its own spinlock. A process stores
only its `gid`, not a private budget. Slots persist until reboot; exit and
reparenting do not create fresh balances. Fork copies the parent's `gid` before
the child becomes runnable. Successful or failed exec leaves `gid` unchanged.

Group 0 is the trusted administrator group. The kernel accepts `setbudget(gid,
max, refill_per_100_ticks, mode)` only from a group-0 process. It accepts one
successful configuration per group per boot; a duplicate call returns `-1` and
cannot reset `remaining`. The check and update occur under the target group's
lock, with lock order `tickslock` then group lock. Gids must be in range;
`max` and refill are signed integers from 0 to 2147483647; modes are
`BUDGET_FAIL` (0) and `BUDGET_BLOCK` (1). A refill larger than maximum is valid.
Invalid calls leave the group unchanged.

`setgroup(gid)` lets a group-0 process enter an already configured nonzero
group. The caller alone changes membership. Once in a nonzero group, it cannot
enter another group or return to group 0. Naming the current gid is a harmless
success. Entry into an unconfigured group fails. The configured flag never
reverts, so checking it under the group lock before changing the caller's gid
is safe even after releasing that lock.

`init` configures both groups before console creation or starting the shell:

| Group | Maximum | Refill per 100 ticks | Mode | Use |
| --- | ---: | ---: | --- | --- |
| 0 | 10000 | 1000 | BLOCK | Trusted init and administrator shell |
| 1 | 1000 | 100 | FAIL | Default workload |

The boot shell stays in group 0. Its `budget gid max refill fail|block` built-in
configures an unused nonzero group; `0` and `1` also name the modes. The shell
rejects invalid or overflowing decimal arguments and extra tokens. Its
`group gid` built-in selects a configured nonzero group for later commands. A
short-lived child probes membership so selection never changes the shell's
own gid or the group's configuration. After a shell restart, selection returns
to group 1, but configured groups remain available until reboot.

For every ordinary command line, the shell forks and the child enters the
selected group before command parsing, redirection, file creation, truncation,
or exec. Failed assignment exits the child without running the command.
Pipelines, background jobs, lists, and parenthesized commands fork or recurse
after this transition, so descendants inherit it. `cd`, `budget`, and `group`
are trusted shell built-ins; a shell launched inside a workload group cannot
configure budgets or move to another group. If that workload shell inherited
a gid other than 1, it must select its own gid before launching commands;
otherwise the child assignment fails closed.

Group 0 has a configured budget and **has no exemption in the charge
function**. Unlink, positive console and regular-file writes, user exec,
create/truncate, mkdir, mknod, and link are charged. The group table
implements FAIL, BLOCK, lazy refill, and statistics. The trusted shell can
run `relay command` (or `relaybg command`) to pay for a selected workload's
diagnostic console output while the child stays in its workload group. The
approved table and exact charging paths are in
[`design.md`](design.md).

## Trust boundary and verification

xv6 has no user identities or filesystem permission model. This design trusts
`init`, the group-0 shell, its operator, and their executable images. A program
deliberately executed in group 0 would have administrator authority. A hostile
workload that can replace `/sh` on disk and cause it to restart is outside the
current protection boundary; protecting trusted binaries requires later work.
No group is reclaimed during a boot. An exhausted zero-refill group cannot be
reset by a workload.

Build with `make -j2` and, after preserving any personal image data,
`make -j2 fs.img`, then `make qemu`. On a fresh boot, run `hello`,
`groupauth`, `grouptest`, and `forktest`. Run `usertests -q` through
`tests/regression.py`, which configures a large dedicated group. To exercise
an independent group, reserve gid 15 for this test and run:

```text
budget 15 1000 100 fail
budget 15 1000 100 fail
group 15
groupauth selected
grouptest test
group 1
grouptest
```

The second `budget` command must be refused because gid 15 is already
configured. `grouptest` itself never configures a slot; its `test` mode expects
the shell to select reserved gid 15 first. The old administrator-only
`groupauth admin` mode retains invalid-argument and concurrent
first-configuration tests, using reserved gids 12, 13, and 14. The disposable
`tests/admin_boot.py` harness runs it from a temporary copy of `init` before
shell startup; the ordinary shell assigns workload membership before exec and
cannot run an administrator-mode test.
Workload-mode `groupauth` and `grouptest` can run repeatedly without consuming
slots. See [`demo.md`](demo.md) for a fresh-boot presentation.
