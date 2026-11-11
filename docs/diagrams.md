# UndoBudget presentation diagrams

These diagrams describe the implementation in this repository. GitHub renders
the Mermaid blocks directly. For slides, copy each block into a Mermaid renderer
and export it as SVG or PNG. The approved prices are engineering choices for
this project, not numbers assigned by the reference PDF.

## 1. Architecture: where each decision is made

```mermaid
flowchart LR
    subgraph Host[Host computer]
      JSON[JSON tool request] --> V[Python validator<br/>six allowed tools]
      V --> E[Deterministic executor]
      E --> B[QEMU serial bridge<br/>request ID and framed reply]
    end

    subgraph Guest[xv6 user space]
      I[init: configure groups 0 and 1 once] --> S[Shell stays in group 0]
      S -->|budget: configure unused group| CFG[setbudget syscall]
      S -->|group: select workload gid| SEL[Selected gid in shell state]
      SEL -->|fork; child calls setgroup| P[Workload process]
      P -->|fork copies gid| C[Child and descendants]
      P -->|exec preserves gid| P
      B -->|bounded relay command| H[agentop helper in workload group]
      H -->|file and status syscalls| K
      P --> K[Charged syscalls]
      C --> K
      S -->|budgetstat command| ST[Snapshot syscall]
    end

    subgraph Kernel[xv6 kernel]
      CFG --> AUTH[Group-0-only authorization<br/>one configuration per group]
      AUTH --> G[groups 0..15<br/>one lock and one shared balance per group]
      K --> HOOK[Operation-specific charge sites<br/>unlink, open, link, mkdir, mknod,<br/>file/console write, user exec]
      HOOK --> CH[group_charge / group_try_charge]
      CH --> G
      T[Timer ticks] --> CH
      G -->|FAIL: refuse; BLOCK: wait or admit| HOOK
      HOOK -->|admitted operation| FS[Filesystem / console / exec effect]
      FS --> IN[Inode creator_gid<br/>memory and disk; written by mkfs]
      ST -->|locked value snapshot| G
    end
    ST -->|copyout: balance, mode, counters| S
    H -->|framed result, never console echo as success| B
```

**Present it in this order:** `init` sets the initial policy; the trusted shell
keeps gid 0 and sends each ordinary command into a configured workload group;
fork and exec cannot create a fresh balance; charge sites consult the single
locked group slot before an effect. The Python side validates requests and
reports only a verified guest result. `creator_gid` distinguishes the two
regular-file write prices. `budgetstat` exposes a read-only snapshot.

## 2. Flowchart: one positive-cost operation

```mermaid
flowchart TD
    A[User command or validated agent request] --> B[Shell child enters selected workload group]
    B --> C[Kernel receives syscall]
    C --> D{Arguments / path / descriptor valid<br/>for this charge site?}
    D -->|No| BAD[Return error; no charge at that site]
    D -->|Yes| PRICE[Compute one approved cost<br/>operation and requested byte count;<br/>file writes compare creator_gid]
    PRICE --> FREE{Cost is zero?}
    FREE -->|Yes| EFFECT[Perform operation]
    FREE -->|No| LOCK[Read ticks; lock group slot;<br/>apply full 100-tick refill periods]
    LOCK --> CONF{Group configured<br/>and cost attainable?}
    CONF -->|No| REFUSE[Return refusal; no intended effect]
    CONF -->|Yes| FUNDS{Enough remaining now?}
    FUNDS -->|Yes| DEDUCT[Deduct once atomically;<br/>increment allowed counter]
    DEDUCT --> EFFECT
    FUNDS -->|No, FAIL| REFUSE
    FUNDS -->|No, BLOCK| WAIT[Register on ticks channel;<br/>drop locks; sleep]
    WAIT -->|timer wake / kill| RECHECK{Killed?}
    RECHECK -->|Yes| REFUSE
    RECHECK -->|No| LOCK
    EFFECT --> RESULT[Return syscall result;<br/>no refund for later failure]
    REFUSE --> STATUS[Optional budgetstat snapshot<br/>and file-state check]
    RESULT --> STATUS
    STATUS --> OUT[Agent gets framed guest status;<br/>shell sees syscall result]
```

**Important qualification:** `unlink` validates its target and nonempty
directory condition before charging. Its BLOCK retry releases inode locks and
the log transaction, waits, then revalidates the target and attempts the actual
charge. Other charged calls can fail after admission and keep their charge.
For file writes, the price uses the **requested** positive byte count, once per
syscall, even if a later write is partial. A zero-cost call leaves counters
unchanged. `budgetstat` reports stored balance; lazy refill happens on a charge.

### Costs to point to during the demonstration

| Operation | Cost per admitted call |
| --- | ---: |
| Unlink | 12 |
| Console write, `n > 0` | `2 + ceil(n/128)` |
| Same creator-group regular-file write, `n > 0` | `2 + ceil(n/1024)` |
| Cross creator-group regular-file write, `n > 0` | `6 + 2 × ceil(n/1024)` |
| Open with `O_CREATE`, `O_TRUNC`, or both | 4, 10, or 14 |
| `mkdir` or `mknod`; `link`; user `exec` | 6; 3; 4 |
| Everything else | 0 |

For a live walkthrough, use the exact commands in [demo.md](demo.md). A
refused `unlink` needs both its error and the surviving file to demonstrate
that the irreversible effect was prevented. For BLOCK, show a waiting command,
the timer refill, then its eventual success and changed counters.
