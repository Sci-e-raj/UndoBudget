# UndoBudget design journal

This journal records **decisions visible in the current tree**. It is not a
commit history or a claim that every approved cost has been enforced. The
reference `xv6_projects.pdf` supplied the problem statement and illustrative
costs; the numerical table in [`design.md`](design.md) is the team's approved
engineering policy.

| Decision | Reason and code evidence | Verification / remaining edge |
| --- | --- | --- |
| Use 16 persistent group slots, with only `gid` in each process. | `kernel/group.c` holds shared balances and per-group locks; `kernel/proc.c` copies `gid` in `kfork()`. Exit does not reset a slot. | `grouptest`, `budgettest shared`, and concurrent charge tests cover inheritance and sharing. |
| Trust group 0 for one-time configuration; make workload membership one-way. | `ksetbudget()` checks caller gid and atomically sets `configured`; `ksetgroup()` permits only configured destinations from group 0. `init` configures groups 0 and 1 before shell startup; `sh` assigns children before parsing/redirection. | `groupauth` workload cases and shell tests pass. Trusted administrator-mode `groupauth admin` is not runnable through the ordinary workload shell; a separate trusted bootstrap harness is still needed. |
| Choose one up-front charge with no refund. | A refused operation must not produce its intended effect; retaining a charge after later failure avoids rollback bookkeeping. `sys_unlink` checks target validity before charge; `filewrite` charges requested length once before log writes. | Missing targets and nonempty directories are free. Invalid regular-file user buffers can still be charged before `writei` rejects them; document this limit. |
| Persist creator ownership in the inode. | `creator_gid` is 32-bit on disk and in memory; `ialloc` zeroes reused records and sets the creator, `ilock` loads it, `iupdate` saves it, and mkfs marks boot files group 0. | Creator persistence/reuse tests pass on CPUS=1/3. Old disk images require rebuilding due 68-byte inodes, `IPB=15`, and magic `0x10203041`. |
| Enforce unlink and ownership-aware regular-file writes at operation-specific sites. | `sys_unlink` charges 12 after validation and before directory update. `filewrite` reads creator gid under inode lock, unlocks, then charges `2+ceil(n/1024)` or `6+2ceil(n/1024)`. | `unlinkbudget`, `writebudget`, race, and refusal-survival cases pass. Approved console, open, directory, link, and flat exec costs remain unenforced. |
| Refill lazily and make BLOCK wait on ticks. | `setbudget` records `last_refill`; the charge path applies full 100-tick periods with a cap. `sleep_prepare(&ticks)` happens under `tickslock`; no spinlock or filesystem transaction is held across sleep. | Host boundary tests and QEMU BLOCK/refill tests pass. `n_blocked` records registrations, potentially many per call. Multiple whole 32-bit tick wraps between charges are not distinguishable. |
| Expose value-only snapshots. | `kbudgetstat` checks gid and destination size, snapshots under the group lock, then `copyout`s after release. The user command prints all 16 slots. | Invalid-buffer and concurrent-snapshot tests pass. A snapshot does not itself apply lazy refill or atomically sample several groups. |
| Keep the agent deterministic and fail closed. | Python validation restricts JSON, paths, sizes, and tool names; the serial bridge requires a unique matching `UB1` completion frame from `agentop`. | Agent unit, smoke, and end-to-end budget tests pass. Four tools run end to end; `write_file` and `execute_program` are validated but unsupported. An active serial timeout leaves guest effect unknown and invalidates the bridge session; a queued timeout sends no request. |
| Collect measurements independently of kernel behavior. | `experiments/collect.py` uses fresh scratch images and retains raw serial logs plus CSV; `plot.py` reads only PASS rows. Independent jobs buffer observations to avoid this xv6 console's 32-byte write-chunk interleaving. | The 2026-11-06 run passed 10/10 scenario/CPU combinations with 134 observed rows; figures are derived from CSV, with missing runs labeled. |

## Current evidence

- On 2026-11-06, `python3 tests/regression.py` finished **24 PASS, 0 FAIL,
  2 UNTESTED**. Its generated JSON report was
  `/tmp/undobudget-regression-i16614ez.json` in the test environment. The
  untested rows are `groupauth-admin-mode` (needs trusted boot execution) and
  `exec-ownership-cost` (no ownership-dependent exec cost is assigned; the
  approved flat cost 4 is not yet enforced). The PASS rows include
  `usertests -q` on CPUS=1 and CPUS=3, creator persistence/reuse, BLOCK
  waiters, ownership-aware writes, and agent tests. `/tmp` reports are
  temporary; rerun the command to produce local evidence.
- On 2026-11-06, `python3 experiments/collect.py --cpus 1 3` finished
  **10 PASS, 0 FAIL**, with **134** guest observations. Its raw logs and CSV
  were under `/tmp/undobudget-evaluation-20261106T065217Z/` in the test
  environment. FAIL admitted 4 of 6 deletions from 48 units on each CPU
  count; BLOCK admitted 4 deletions with refill over about 300 guest ticks;
  eight contenders admitted exactly 4 of 8 deletions from 48 units. See
  [`../experiments/README.md`](../experiments/README.md) to regenerate.
- On 2026-11-06, the 21 guest commands in [`demo.md`](demo.md) passed in
  sequence on one fresh CPUS=1 scratch image, including the helper's
  `unlink_failed_budget_possible` response and the surviving file. The host
  validator independently returned `invalid_path` for `../bsp`. The
  verification transcript was `/tmp/undobudget-demo-verification.log` in
  that test environment; it is temporary.

## Remaining design work

Implement the approved costs that are still listed as planned in
[`design.md`](design.md), using operation-specific validation and charging
sites. A file's creator gid is already stored, but its presence does not make
exec ownership-sensitive: user exec has a **flat planned cost of 4**. Review
trusted binary protection before presenting group 0 as a security boundary.
No future operation should sleep with an inode lock or filesystem transaction
held. Do not treat a QEMU timeout or a transport error as evidence of budget
refusal or successful operation.
