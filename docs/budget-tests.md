# FAIL-mode unlink accounting tests

The approved unlink cost is **12 per admitted call**. The handout's 10-unit
example is illustrative, so these tests use 12. `user/budgettest.c` reserves
gids 2 through 7; group 0 and 1 are configured by `init`, and other existing
tests reserve gids 11, 13, 14, and 15. No test here calls `setbudget` to reset
a group. Run the sequence once per fresh boot because configuration and spent
balances persist until reboot. Fixture names also require a fresh filesystem.

Build and start xv6, setting `CPUS=1` or `CPUS=3`:

```sh
make -j2
make -B -j2 fs.img
make qemu CPUS=1
```

At the xv6 shell, run:

```text
budget 2 50 0 fail
budget 3 12 0 fail
budget 4 12 0 fail
budget 5 12 0 fail
budget 6 12 0 fail
budget 7 11 0 fail
group 2
budgettest fifty
group 3
budgettest shared
group 4
budgettest first
group 5
budgettest second
group 6
budgettest race
group 7
budgettest boundary
```

Each mode must print `budgettest: PASS <mode>`. `fifty` creates all six files
before deletion, admits four calls (48 units), and verifies that the next two
files survive refusal. `shared` has a child spend the only 12 units and checks
that the parent's target survives. `first` exhausts gid 4, then `second`
proves gid 5 still has its own 12 units. `race` releases four forked children
together: exactly one deletion must succeed and three files must survive on
both one and three CPUs. `boundary` checks invalid group/configuration
arguments and proves that 11 units cannot pay a 12-unit unlink cost.

`group_charge(long cost)` is a kernel-only function, so an xv6 user program
cannot supply a negative raw charge cost. The `boundary` mode covers the
observable cost threshold. Run the direct API test against the actual
`kernel/group.c` implementation from the repository root:

```sh
gcc -std=gnu99 -fno-builtin -I. kernel/group.c tests/group_charge_host.c -o /tmp/group_charge_host
/tmp/group_charge_host
```

It checks invalid gids, negative and oversized costs, zero cost, and a
positive charge against an unconfigured group. All positive-cost xv6 test
groups use zero refill and FAIL mode.
