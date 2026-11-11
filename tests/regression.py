#!/usr/bin/env python3
"""Run UndoBudget host and xv6 regressions without touching repository fs.img.

From the repository root: python3 tests/regression.py
Each QEMU suite gets a fresh scratch image except the two creator probes,
which deliberately reboot the same scratch image to verify persistence.
"""

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from blockstress import Guest, build_image


ROOT = Path(__file__).resolve().parents[1]
results = []


def record(name, cpus, commands, action):
    try:
        detail = action()
        status = "PASS"
    except Exception as exc:
        status = "FAIL"
        detail = f"{type(exc).__name__}: {exc}"
    results.append({"suite": name, "cpus": cpus, "status": status,
                    "commands": commands, "detail": detail})
    print(f"{status:4} CPUS={cpus or '-'} {name}: {detail}", flush=True)


def run_command(command, timeout=120):
    completed = subprocess.run(command, cwd=ROOT, text=True,
                               capture_output=True, timeout=timeout)
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise AssertionError(f"{' '.join(command)} exited {completed.returncode}: "
                             f"{output[-1400:]}")
    return output[-400:]


def guest_steps(image, cpus, steps):
    guest = Guest(image, cpus)
    command = "<boot>"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            guest.expect(r"\$ ", 25)
            for command, patterns, timeout in steps:
                guest.send(command)
                for pattern in patterns:
                    guest.expect(pattern, timeout)
                guest.expect(r"\$ ", min(timeout, 20))
        return f"{len(steps)} commands passed"
    except Exception as exc:
        raise AssertionError(f"after {command!r}: {exc}; serial tail: "
                             f"{guest.output[-1200:]!r}") from exc
    finally:
        guest.close()


def image_suite(directory, name, cpus, steps):
    image = directory / f"{name}-{cpus}.img"
    with contextlib.redirect_stdout(io.StringIO()):
        build_image(image)
    return guest_steps(image, cpus, steps)


def creator_suite(directory, cpus):
    image = directory / f"creator-{cpus}.img"
    with contextlib.redirect_stdout(io.StringIO()):
        build_image(image)
    guest_steps(image, cpus, [
        ("budget 2 100 0 fail", [r"budget: group 2 configured"], 10),
        ("group 2", [r"group: using 2"], 10),
        ("relay creatorprobe create", [r"creatorprobe: PASS create inum [0-9]+"], 15),
        ("sync", [], 10),
    ])
    first = run_command([sys.executable, "tests/check_creator_inode.py",
                         str(image), "cg_old", "2"])
    guest_steps(image, cpus, [
        ("budget 3 100 0 fail", [r"budget: group 3 configured"], 10),
        ("group 3", [r"group: using 3"], 10),
        ("relay creatorprobe replace", [r"creatorprobe: PASS replace inum [0-9]+"], 15),
        ("sync", [], 10),
    ])
    second = run_command([sys.executable, "tests/check_creator_inode.py",
                          str(image), "cg_new", "3", "--absent", "cg_old"])
    old_inum = re.search(r"inum=([0-9]+)", first)
    new_inum = re.search(r"inum=([0-9]+)", second)
    assert old_inum and new_inum and old_inum.group(1) == new_inum.group(1), \
        f"inode was not reused: {first}; {second}"
    return f"creator persisted across reboot; inode {old_inum.group(1)} reused"


BOOT_AUTH = [
    ("relay budgetstat", [r"0\s+yes\s+BLOCK\s+[0-9]+/\s*10000",
                    r"1\s+yes\s+FAIL\s+996/\s*1000"], 15),
    ("hello", [r"hello: PASS"], 15),
    ("groupauth", [r"groupauth: PASS \(default workload\)"], 20),
    ("grouptest", [r"grouptest: PASS \(group 1\)"], 20),
    ("forktest", [r"fork test OK"], 45),
    ("budget 15 100 0 fail", [r"budget: group 15 configured"], 10),
    ("group 15", [r"group: using 15"], 10),
    ("relay groupauth selected", [r"groupauth: PASS \(selected group\)"], 20),
    ("relay grouptest test", [r"grouptest: PASS \(group 15\)"], 20),
]

FAIL_ACCOUNTING = [
    ("budget 11 34 0 fail", [r"budget: group 11 configured"], 10),
    ("group 11", [r"group: using 11"], 10),
    ("relay unlinkbudget", [r"unlinkbudget: PASS"], 20),
    *((f"budget {gid} {maximum} 0 fail", [rf"budget: group {gid} configured"], 10)
      for gid, maximum in ((2, 78), (3, 24), (4, 24), (5, 24), (6, 32), (7, 8))),
    *((command, [pattern], 30)
      for gid, mode in ((2, "fifty"), (3, "shared"), (4, "first"),
                        (5, "second"), (6, "race"), (7, "boundary"))
      for command, pattern in ((f"group {gid}", rf"group: using {gid}"),
                               (f"relay budgettest {mode}", rf"budgettest: PASS {mode}"))),
]

WRITE_OWNERSHIP = [
    *((f"budget {gid} {maximum} 0 fail", [rf"budget: group {gid} configured"], 10)
      for gid, maximum in ((8, 15), (9, 19), (10, 20))),
    *((command, [pattern], 20)
      for gid, mode in ((8, "same"), (9, "cross-deny"), (10, "cross-allow"))
      for command, pattern in ((f"group {gid}", rf"group: using {gid}"),
                               (f"relay writebudget {mode}", rf"writebudget: PASS {mode}"))),
]

REFILL = [
    ("budget 8 24 12 fail", [r"budget: group 8 configured"], 10),
    ("group 8", [r"group: using 8"], 10),
    ("relay refillbudget", [r"refillbudget: PASS \(elapsed [0-9]+ ticks\)"], 30),
]

SNAPSHOTS = [
    ("budget 12 40 0 fail", [r"budget: group 12 configured"], 10),
    ("group 12", [r"group: using 12"], 10),
    ("relay budgetstat race", [r"budgetstat: PASS race"], 30),
    ("budget 13 11 3 block", [r"budget: group 13 configured"], 10),
    ("group 13", [r"group: using 13"], 10),
    ("relay budgetstat block", [r"budgetstat: PASS block"], 45),
]

BLOCK_REFILL = [
    ("budget 12 24 12 block", [r"budget: group 12 configured"], 10),
    ("group 12", [r"group: using 12"], 10),
    ("relay blockrefill", [r"blockrefill: PASS \([0-9]+ ticks\)"], 55),
]

FS_COSTS = [
    ("budget 14 200 0 fail", [r"budget: group 14 configured"], 10),
    ("group 14", [r"group: using 14"], 10),
    ("relay fsbudget costs", [r"fsbudget: PASS costs"], 20),
    ("budget 15 6 0 fail", [r"budget: group 15 configured"], 10),
    ("group 15", [r"group: using 15"], 10),
    ("relay fsbudget deny", [r"fsbudget: PASS deny"], 20),
]

EXEC_COSTS = [
    ("budget 15 7 0 fail", [r"budget: group 15 configured"], 10),
    ("group 15", [r"group: using 15"], 10),
    ("relay execbudget deny", [r"execbudget: PASS deny"], 15),
    ("budget 14 200 0 fail", [r"budget: group 14 configured"], 10),
    ("group 14", [r"group: using 14"], 10),
    ("relay execbudget allow", [r"hello: PASS"], 15),
]

CONSOLE_COSTS = [
    ("budget 15 7 0 fail", [r"budget: group 15 configured"], 10),
    ("group 15", [r"group: using 15"], 10),
    ("relay consolebudget 128", [r"consolebudget: PASS 128"], 15),
    ("budget 14 8 0 fail", [r"budget: group 14 configured"], 10),
    ("group 14", [r"group: using 14"], 10),
    ("relay consolebudget 129", [r"consolebudget: PASS 129"], 15),
]

USERTESTS = [
    ("budget 10 2147483647 2147483647 fail",
     [r"budget: group 10 configured"], 10),
    ("group 10", [r"group: using 10"], 10),
    ("usertests -q", [r"ALL TESTS PASSED"], 600),
]


def main():
    with tempfile.TemporaryDirectory(prefix="undobudget-regression-") as temp:
        directory = Path(temp)
        record("build", None, ["make -j2", "make -j2 user/_agentop"],
               lambda: run_command(["make", "-j2"]) + "; " +
               run_command(["make", "-j2", "user/_agentop"]))
        record("host-charge-boundaries", None,
               ["gcc -std=gnu99 -fno-builtin -pthread -I. kernel/group.c "
                "tests/group_charge_host.c -o <temp>/group_charge_host",
                "<temp>/group_charge_host"],
               lambda: (run_command(["gcc", "-std=gnu99", "-fno-builtin", "-pthread",
                                     "-I.", "kernel/group.c", "tests/group_charge_host.c",
                                     "-o", str(directory / "group_charge_host")]),
                        run_command([str(directory / "group_charge_host")]))[-1])
        record("agent-validation-bridge-timeouts", None,
               ["python3 -m unittest discover -s tests -p test_agent_*.py -q"],
               lambda: run_command([sys.executable, "-m", "unittest", "discover",
                                    "-s", "tests", "-p", "test_agent_*.py", "-q"]))
        record("agent-helper-smoke", 3, ["python3 tests/agent_smoke.py"],
               lambda: run_command([sys.executable, "tests/agent_smoke.py"], 60))

        for cpus in (1, 3):
            for name, steps in (("boot-auth-fork-exec", BOOT_AUTH),
                                ("fail-shared-accounting", FAIL_ACCOUNTING),
                                ("write-creator-costs", WRITE_OWNERSHIP),
                                ("refill-smoke", REFILL),
                                ("budget-snapshots", SNAPSHOTS),
                                ("block-refill", BLOCK_REFILL),
                                ("filesystem-costs", FS_COSTS),
                                ("exec-costs", EXEC_COSTS),
                                ("console-costs", CONSOLE_COSTS),
                                ("usertests", USERTESTS)):
                commands = [step[0] for step in steps]
                record(name, cpus, commands,
                       lambda name=name, steps=steps, cpus=cpus:
                       image_suite(directory, name, cpus, steps))
            record("creator-persistence-reuse", cpus,
                   ["creatorprobe create", "check_creator_inode.py cg_old 2",
                    "<reboot>", "creatorprobe replace",
                    "check_creator_inode.py cg_new 3 --absent cg_old"],
                   lambda cpus=cpus: creator_suite(directory, cpus))
            record("administrator-boot", cpus,
                   [f"python3 tests/admin_boot.py {cpus}"],
                   lambda cpus=cpus: run_command(
                       [sys.executable, "tests/admin_boot.py", str(cpus)], 90))
            record("block-waiters-independent", cpus,
                   [f"python3 tests/blockstress.py {cpus}"],
                   lambda cpus=cpus: run_command(
                       [sys.executable, "tests/blockstress.py", str(cpus)], 360))
            record("agent-kernel-end-to-end", cpus,
                   [f"python3 tests/agent_budget_e2e.py {cpus}"],
                   lambda cpus=cpus: run_command(
                       [sys.executable, "tests/agent_budget_e2e.py", str(cpus)], 90))

        for row in results:
            if row["status"] == "UNTESTED":
                print(f"UNTESTED CPUS=- {row['suite']}: {row['detail']}", flush=True)

        report = directory / "regression.json"
        report.write_text(json.dumps(results, indent=2) + "\n")
        with tempfile.NamedTemporaryFile(prefix="undobudget-regression-",
                                         suffix=".json", delete=False) as target:
            target.write(report.read_bytes())
            persistent = Path(target.name)
        print(f"Report: {persistent}", flush=True)
        print(f"Summary: {sum(r['status']=='PASS' for r in results)} pass, "
              f"{sum(r['status']=='FAIL' for r in results)} fail, "
              f"{sum(r['status']=='UNTESTED' for r in results)} untested", flush=True)
    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
