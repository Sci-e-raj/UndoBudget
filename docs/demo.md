# Short UndoBudget demonstration

Use a **fresh image**: `setbudget` is one-time per group per boot, and these
tests create fixed filenames. The commands below use gids 3, 4, 5, and 12 on
one boot; do not first run other tests that reserve them. This script shows
implemented behavior only. For a shorter presentation, prebuild the image
before the audience arrives. The 21 xv6 commands below passed in sequence on
a fresh CPUS=1 scratch image on 2026-11-06; the host invalid-path example was
also checked separately.

## 1. Boot a scratch image (host terminal A)

From the repository root, with the RISC-V toolchain and QEMU on `PATH`:

```sh
make -j2
DEMO_DIR=$(mktemp -d /tmp/undobudget-demo.XXXXXX)
python3 - "$DEMO_DIR/fs.img" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "tests")
from blockstress import build_image
build_image(Path(sys.argv[1]))
PY
qemu-system-riscv64 -machine virt -bios none -kernel kernel/kernel -m 128M \
  -smp 1 -nographic -global virtio-mmio.force-legacy=false \
  -drive file="$DEMO_DIR/fs.img",if=none,format=raw,id=x0 \
  -device virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0
```

The shell prompt proves that `init` configured group 0 and group 1 before
launch. At the xv6 prompt:

```text
budgetstat
```

Point to group 0 (`10000/10000`, BLOCK) and group 1 (`1000/1000`, FAIL).
Group 0 is trusted for configuration, but its charge function has no
administrator exemption. Console output and user exec are not charged yet.

## 2. Configure, inherit, and refuse (xv6 prompt)

```text
budget 3 12 0 fail
group 3
budgettest shared
budgetstat
```

Expected: `budgettest: PASS shared`. The forked child removes `bsc` for 12
units. The parent shares the same gid and balance, so its attempt to delete
`bsp` is refused; the test checks that `bsp` survives. The group-3 row shows
remaining 0, allowed 1, refused 1. `budget` and `group` are shell built-ins;
the shell itself stays in group 0, while ordinary children enter group 3.

## 3. BLOCK, refill, and snapshot (xv6 prompt)

```text
budget 12 12 12 block
group 12
blockrefill
budgetstat
```

Expected: `blockrefill: PASS (<ticks> ticks)`. The program performs five
same-group one-byte writes and one unlink; it waits as needed for full
100-tick refills. Its final checks prove that the writes and unlink took
effect. The group-12 row shows six allowed charges, at least one blocked wait
registration, no refusals, and remaining 0. `n_blocked` can be much larger
than the number of calls because the timer can wake and re-register a waiter
on successive ticks. `budgetstat` reads stored lazy-refill state; it does not
itself refill the group.

## 4. Show agent rejection and surviving target

Return the shell's selected workload to exhausted group 3:

```text
group 3
agentop demo-fail delete_file bsp
ls bsp
budgetstat
```

The helper should emit `UB1|demo-fail|END|ERR|unlink_failed_budget_possible`.
The helper's error name alone does not prove the cause: xv6 returns `-1` for
ordinary unlink failures too. Here `bsp` is still listed and group 3's
`n_refused` rises by one, which together show a budget refusal in this
controlled demo.

In **host terminal B**, also show rejection before a request reaches QEMU:

```sh
python3 - <<'PY'
import json
from undobudget_agent.validation import validate_request
request = {"request_id": "bad-path", "tool": "delete_file",
           "arguments": {"path": "../bsp"}}
print(validate_request(json.dumps(request)))
PY
```

Expected: `ok: False` with `error.code: invalid_path`. This demonstrates the
Python validator; the `agentop` command above demonstrates the guest helper
and kernel. For the complete Python bridge → helper → kernel budget-refusal
trace on its **own fresh image**, run `python3 tests/agent_budget_e2e.py 1`
after the live session. It prints a JSON report path and must report PASS.

## 5. Show two independent groups (back at xv6 prompt)

```text
budget 4 12 0 fail
budget 5 12 0 fail
group 4
budgettest first
budgetstat
group 5
budgettest second
budgetstat
```

Each test prints `budgettest: PASS <mode>`. After group 4 spends its 12 units,
the first snapshot still shows group 5 with 12 untouched units. Group 5 then
spends its own 12 units. Both tests verify that a second deletion is refused
and its target survives. The shell's `group` selection does **not** transfer
or reset a balance. Exit QEMU with `Ctrl-a x`.

For graphical evidence after the demo, use
`python3 experiments/collect.py --cpus 1 3 --output /tmp/undobudget-figures`
on a new output path, followed by
`python3 experiments/plot.py /tmp/undobudget-figures`. It creates new scratch
images and never rewrites the image used above.
