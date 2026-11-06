# UndoBudget viva questions and defensible answers

Use [`design.md`](design.md) for the exact policy and current code status.
Answers below describe this repository as tested; they do not turn planned
charges into implemented features.

1. **What is an irreversibility budget?** A shared allowance assigned to a
   process group. Selected kernel operations deduct from it before effects.
   This tree currently enforces it for unlink and positive regular-file
   writes. Reads and other unlisted operations remain free.

2. **Why store only a gid in `struct proc`?** The balance lives in one
   `groups[NGROUP]` slot protected by its lock. Fork copies the gid, so parent
   and child compete for the same points. A per-process balance would be
   duplicated by fork and could be spent more than once.

3. **Can a process fork, exec, exit, or change parent to obtain new points?**
   No. Fork inherits gid; exec preserves it; reparenting and exit do not
   recreate or reset a group slot. A workload cannot switch gid or return to
   group 0. Slots live until reboot.

4. **Who can configure budgets?** A process currently in group 0. The kernel
   checks this in `ksetbudget`, and the configured flag can change from false
   to true only once under the target group lock. The shell's `budget` command
   is an administrator built-in, not a privilege grant to its workloads.

5. **Does group 0 bypass charging?** No: `group_charge` has no group-0 special
   case, and `init` gives it a BLOCK budget of 10000 with refill 1000/100
   ticks. Console output and exec are currently uncharged for *all* groups,
   because those policy hooks are not implemented.

6. **Where does the kernel charge unlink?** In `sys_unlink`, after the path,
   target, dot-name, and nonempty-directory checks, and immediately before
   the directory entry is cleared. A FAIL refusal leaves the target intact.
   A failure after that charge is not refunded.

7. **Why is a generic syscall-dispatch charge inadequate?** Dispatch lacks
   the validated target inode, file descriptor type, creator gid, and the
   precise first-effect point. Unlink and file writes need distinct sites so
   invalid calls and rejected effects are handled correctly.

8. **How are same-group and cross-group writes priced?** For positive `n`,
   a regular-file write costs `2+ceil(n/1024)` when the caller's gid equals
   the inode's creator gid, otherwise `6+2ceil(n/1024)`. The charge is once
   for the requested write syscall, even when filewrite splits log
   transactions. A 4097-byte write costs 7 or 16 respectively.

9. **Does the cost scale per byte?** No. It is one charge per call, with a
   size-dependent step term for writes. The approved console formula is
   `2+ceil(n/128)` but is not yet enforced. A zero-byte write is free. The
   numeric values are engineering choices, not a mathematical optimum or
   mandatory values from the reference PDF.

10. **What happens on invalid or failed calls?** `sys_unlink` rejects bad
    paths, missing targets, and nonempty directories before charging.
    `sys_write` rejects bad fds and negative lengths first. An admitted
    operation that later fails keeps its charge. In the current file-write
    path, user data is copied after charging, so an invalid positive user
    pointer may be charged before the copy fails; say this explicitly.

11. **How is creator ownership persisted and reused safely?** The disk and
    memory inode have `creator_gid`. `ialloc` clears a reused disk record and
    sets the creating process's gid; `ilock` loads and `iupdate` persists it.
    `mkfs` assigns group 0 to boot files. The disk inode is 68 bytes, `IPB`
    is 15, and magic `0x10203041` rejects old-format images.

12. **How does lazy refill work?** `setbudget` records current ticks.
    On a later charge, whole elapsed 100-tick periods are applied, the
    remainder is retained, and balance is capped at maximum. Arithmetic
    checks room before multiplying rate by periods. A read-only snapshot
    does not cause refill.

13. **How does BLOCK avoid lost wakeups?** The charge loop holds `tickslock`
    while checking affordability and calling this tree's
    `sleep_prepare(&ticks)`. It releases locks before `sleep()`. If a timer
    wakeup occurs between registration and sleeping, the registered channel
    is cleared and `sleep()` returns instead of sleeping. Every wake rechecks
    condition and kill state before deducting.

14. **Can BLOCK sleep inside a filesystem transaction or inode lock?** The
    write path releases its inode lock before the potentially sleeping charge.
    Unlink uses nonsleeping `group_try_charge` under its locks. If it needs to
    wait, it releases both inode locks and ends the transaction, waits without
    deducting, then revalidates on retry. A different process can spend the
    refill first, so the retry may wait again.

15. **What do the statistics mean?** `n_allowed` is successful positive
    deductions, even if a later filesystem action fails. `n_refused` is a
    terminal charge refusal, including a killed waiter. `n_blocked` is wait
    registrations, not calls; repeated timer wakeups can make it large.
    Invalid syscall arguments rejected before charging and zero-cost calls
    do not increment these counters.

16. **What if a BLOCK cost exceeds maximum or refill is zero?** The charge
    returns `-1` rather than waiting forever. A killed waiter also returns
    refusal. The balance remains within `[0,max]`.

17. **How does the deterministic agent avoid fabricated success?** Python
    validates exact JSON and safe paths. The bridge serializes requests and
    accepts only matching `UB1` token frames and a terminal `END` record from
    the xv6 helper. The executor parses the framed data. Timeout, broken
    pipe, bad frame, and QEMU exit are not success. An active serial timeout
    leaves the effect unknown and invalidates the session; a queue timeout
    occurs before the request is sent and leaves the active session usable.

18. **Can the agent distinguish every budget refusal from every filesystem
    error?** No. xv6 `unlink` returns `-1` for both. The helper says
    `unlink_failed_budget_possible`; the end-to-end test compares the budget
    snapshot and target existence to establish a controlled budget-refusal
    case. No arbitrary shell strings or LLM are part of this agent.

19. **Which approved features remain untested or unfinished?** The current
    kernel does not charge console writes, create/truncate, mkdir/mknod,
    link, or user exec. The agent validates `write_file` and
    `execute_program` requests but does not execute them. The trusted
    administrator-mode `groupauth` test needs a boot harness because the
    ordinary shell assigns nonzero gid before exec.

20. **What evidence supports the implementation?** The 2026-11-06 regression
    run reported 24 PASS, 0 FAIL, 2 UNTESTED, including `usertests -q` on one
    and three CPUs. A separate evaluation recorded 10 PASS scenario/CPU
    combinations and 134 raw guest observations. Re-run the exact commands
    in [`design.md`](design.md); a timeout is not a pass. These results cover
    the implemented paths, not the planned cost hooks.
