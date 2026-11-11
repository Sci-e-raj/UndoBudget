# UndoBudget evaluation experiments

Run from the repository root:

```sh
python3 experiments/collect.py --cpus 1 3 --output /tmp/undobudget-my-run
python3 experiments/plot.py /tmp/undobudget-my-run
```

The output directory must not already exist. The collector uses the repository's
`tests/blockstress.py` QEMU launcher and `mkfs` recipe to build a **new scratch
filesystem image for each scenario and CPU count**. It does not open or replace
the repository's `fs.img`. QEMU, the RISC-V toolchain, and Python 3 are needed
for collection. Plotting uses only the Python standard library.

The guest program `budgetexp` creates all deletion targets before starting
measurement. Every target is checked after `unlink`: admitted deletions must
remove the file, and refused deletions must leave it intact. It emits `UBEXP`
records; the concurrent independent-group jobs buffer their timed observations
and serialize reporting because this xv6 console splits large writes into
32-byte UART transfers. Each record contains an xv6 uptime
tick, attempted and completed deletion counts, and a locked `budgetstat`
snapshot. The collector keeps the **full raw serial transcript** for each run,
parses those records into `observations.csv`, and writes the result and exact
shell command to `runs.csv`. A failed run keeps its partial transcript and is
excluded from the figures. Unselected or unavailable runs are marked `MISSING`.

| Scenario | Group setup | Measured behavior |
| --- | --- | --- |
| `fail` | gid 2, max 76, refill 0, FAIL | Exec spends 4, six fixtures cost 24, four deletions spend the remaining 48, then two targets survive. |
| `block` | gid 3, max 32, refill 12 per 100 ticks, BLOCK | Four fixtures cost 16; a child deletes four targets while the parent samples refill waits. |
| `shared` | gid 4, max 40, refill 0, FAIL | Three fixtures cost 12; a child and parent each delete once, then the third attempt is refused. |
| `race` | gid 5, max 84, refill 0, FAIL | Eight fixtures cost 32; eight contenders compete for four affordable deletions. |
| `independent` | gids 6 and 7, max 36 and 44, refill 0, FAIL | Four fixtures cost 16 in each group; gid 6 reserves 4 for a completion marker. |

These maxima are **experiment settings**, not operation costs. The enforced
`unlink` cost is 12 units and `open(O_CREATE)` costs 4 per call. Fixture
creations are included in the group maxima; each start snapshot verifies the
resulting balance and allowed counter, including the workload's 4-unit exec.
The trusted shell's `relay` and `relaybg` modes pay for console output from
group 0; the workload writes each measurement to a pipe at zero cost.

`observations.csv` records `tick` and `elapsed_ticks` in xv6 timer units. The
elapsed value is the unsigned 32-bit difference from that group's `start`
record, matching the kernel's single-wrap tick convention. The tick read and
budget snapshot are sequential, not one atomic observation, so a refill or
charge can land between them. `result` is 0 for
a refused attempt, 1 for an admitted attempt, and 2 when a row is an
observation rather than an attempt. The `remaining` column is the stored lazy
refill state: `budgetstat` itself does not apply refill. `allowed` counts
deductions, `blocked` counts wait registrations (possibly more than one per
call), and `refused` counts terminal charge refusals. In the BLOCK scenario,
the parent counts completed deletions by checking which targets are absent;
this avoids treating a charge admitted just before `unlink` finishes as a
completed deletion. The `attempts` field on a sample row counts only observed
outcomes, not an in-flight blocked call.

The plotter reads `runs.csv` and `observations.csv` and saves four SVG files:

- `completed_vs_time.svg`
- `remaining_budget.svg`
- `counter_breakdown.svg`
- `fail_block_comparison.svg`

Only runs marked `PASS` are plotted. Each figure names missing or failed runs.
Tick spacing measures guest behavior under QEMU and includes scheduling and
serial-output overhead; it is not a host-time performance benchmark. For a
quick subset, use `--cases fail block --cpus 1`; omitted runs will be labeled
`MISSING` in the CSV and figures.
