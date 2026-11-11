# FAIL-mode unlink accounting tests

The approved unlink cost is **12 per admitted call**. The handout's 10-unit
example is illustrative, so these tests use 12. `user/budgettest.c` reserves
gids 2 through 7; group 0 and 1 are configured by `init`, and other existing
tests reserve gids 11, 13, 14, and 15. No test here calls `setbudget` to reset
a group. Run the sequence once per fresh boot because configuration and spent
balances persist until reboot. Fixture names also require a fresh filesystem.

For an automatic run on fresh scratch images, use
`python3 tests/regression.py`. To type the sequence below manually, use the
scratch-image boot in [`demo.md`](demo.md); the commands need a new filesystem
and unused group slots. If your repository `fs.img` is disposable, you can
instead build and start it with `CPUS=1` or `CPUS=3`:

```sh
make -j2 kernel/kernel fs.img
make qemu CPUS=1
```

At the xv6 shell, run:

```text
budget 2 78 0 fail
budget 3 24 0 fail
budget 4 24 0 fail
budget 5 24 0 fail
budget 6 32 0 fail
budget 7 8 0 fail
group 2
relay budgettest fifty
group 3
relay budgettest shared
group 4
relay budgettest first
group 5
relay budgettest second
group 6
relay budgettest race
group 7
relay budgettest boundary
```

Each mode must print `budgettest: PASS <mode>`. `fifty` spends 24 units creating
six files, admits four deletions (48 units), and verifies that the next two
files survive refusal. Each workload first spends four units on exec.
`shared` has a child spend the 12 units left after two creations and checks
that the parent's target survives. `first` exhausts gid 4, then `second`
proves gid 5 still has its own 24 units. `race` releases four forked children
together: exactly one deletion must succeed and three files must survive on
both one and three CPUs. `boundary` checks invalid group/configuration
arguments and proves that exec plus the 4-unit creation leaves no points for unlink.

`group_charge(long cost)` is a kernel-only function, so an xv6 user program
cannot supply a negative raw charge cost. The `boundary` mode covers the
observable cost threshold. Run the direct API test against the actual
`kernel/group.c` implementation from the repository root:

```sh
gcc -std=gnu99 -fno-builtin -pthread -I. kernel/group.c tests/group_charge_host.c -o /tmp/group_charge_host
/tmp/group_charge_host
```

It checks invalid gids, negative and oversized costs, zero cost, a positive
charge against an unconfigured group, exact refill boundaries, carried partial
periods, saturation, duplicate configuration, large numeric values, one tick
wrap, and concurrent deductions at a refill boundary. The 32-bit `ticks`
counter cannot reveal multiple complete wraps between charges.

For an xv6 refill smoke test, use a fresh/disposable image and `CPUS=3`, then
run these separate shell commands:

```text
budget 8 24 12 fail
group 8
relay refillbudget
budget 8 1 1 fail
budget 6 32 0 fail
group 6
relay budgettest race
```

`refillbudget` waits at least 105 ticks after spending 8 on fixtures and 12
on its first unlink;
it checks that a later unlink succeeds without asserting an exact scheduler
tick. The second `budget 8` command must be refused. `budgettest race` releases
four children together on three CPUs; exactly one can spend a 12-unit balance.
Preserve any irreplaceable `fs.img` before intentionally forcing a rebuild;
`make -B fs.img` overwrites it. The other `budgettest` groups use zero refill
and FAIL mode. The current tree also charges positive regular-file writes,
as well as creation, truncation, link, mkdir, mknod, console writes, and user
exec. Low-budget diagnostics should use the trusted shell's `relay` command;
see [`design.md`](design.md).
