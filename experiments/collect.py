#!/usr/bin/env python3
"""Collect real xv6 serial logs and budget snapshots on fresh scratch images.

From the repository root: python3 experiments/collect.py --cpus 1 3
Use --output DIR to retain results in a chosen location. No repository fs.img
is opened or replaced. Failed and unselected experiments appear in runs.csv.
"""

import argparse
import contextlib
import csv
import io
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from blockstress import Guest, build_image  # noqa: E402


CASES = {
    "fail": {"budgets": [(2, 76, 0, "fail")], "gid": 2,
             "expected": {2: (4, 2, 0)}},
    "block": {"budgets": [(3, 32, 12, "block")], "gid": 3,
              "expected": {3: (4, 0, None)}},
    "shared": {"budgets": [(4, 40, 0, "fail")], "gid": 4,
               "expected": {4: (2, 1, 0)}},
    "race": {"budgets": [(5, 84, 0, "fail")], "gid": 5,
             "expected": {5: (4, 4, 0)}},
    "independent": {"budgets": [(6, 36, 0, "fail"),
                                 (7, 44, 0, "fail")], "gid": None,
                    "expected": {6: (1, 2, 0), 7: (2, 1, 0)}},
}
OBSERVATION_FIELDS = ["cpus", "scenario", "gid", "event", "tick",
                      "elapsed_ticks", "pid", "attempts", "completed",
                      "result", "remaining", "max", "allowed", "blocked",
                      "refused", "raw_log"]
RUN_FIELDS = ["cpus", "scenario", "status", "detail", "command",
              "host_elapsed_seconds", "raw_log"]
GUEST_FIELDS = {"case", "event", "tick", "gid", "pid", "attempts",
                "completed", "result", "remaining", "max", "allowed",
                "blocked", "refused"}


def parse_observations(log, cpus, scenario, raw_log):
    records = []
    starts = {}
    for line in re.findall(r"UBEXP [^\n]*", log):
        parts = line.split()
        fields = dict(part.split("=", 1) for part in parts[1:]
                      if "=" in part)
        if set(fields) != GUEST_FIELDS:
            raise ValueError(f"malformed guest measurement: {line!r}")
        if fields["case"] != scenario:
            raise ValueError(f"unexpected case in measurement: {line!r}")
        record = {key: int(value) if key not in ("case", "event") else value
                  for key, value in fields.items()}
        gid = record["gid"]
        if record["event"] == "start":
            starts[gid] = record["tick"]
        record["elapsed_ticks"] = (
            (record["tick"] - starts[gid]) & 0xffffffff
            if gid in starts else ""
        )
        record["cpus"] = cpus
        record["scenario"] = record.pop("case")
        record["raw_log"] = raw_log
        records.append(record)
    return records


def validate(records, scenario):
    expected = CASES[scenario]["expected"]
    fixtures = {"fail": 6, "block": 4, "shared": 3, "race": 8,
                "independent": 4}[scenario]
    for gid, (completed, refused, blocked) in expected.items():
        group = [row for row in records if row["gid"] == gid]
        starts = [row for row in group if row["event"] == "start"]
        ends = [row for row in group if row["event"] == "end"]
        if len(starts) != 1 or len(ends) != 1:
            raise AssertionError(f"group {gid}: expected one start and end")
        first, last = starts[0], ends[0]
        if (first["remaining"] != first["max"] - 4 - 4 * fixtures or
                first["allowed"] != 1 + fixtures):
            raise AssertionError(f"group {gid}: fixture costs differ from policy")
        final_remaining = 4 if scenario == "independent" and gid == 6 else 0
        if (last["completed"] != completed or
                last["allowed"] != completed + fixtures + 1 or
                last["refused"] != refused or
                last["remaining"] != final_remaining):
            raise AssertionError(f"group {gid}: unexpected final snapshot: {last}")
        if blocked is not None and last["blocked"] != blocked:
            raise AssertionError(f"group {gid}: unexpected blocked counter")
        if scenario == "block" and last["blocked"] < 3:
            raise AssertionError("BLOCK did not record the expected waits")
        if any(row["remaining"] < 0 or row["remaining"] > row["max"]
               for row in group):
            raise AssertionError(f"group {gid}: balance out of range")
    return "; ".join(f"gid {gid}: {values[0]} completed, {values[1]} refused"
                     for gid, values in expected.items())


def shell_command(guest, command, expected):
    guest.send(command)
    guest.expect(expected, 15)
    guest.expect(r"\$ ", 15)


def run_guest(guest, scenario):
    guest.expect(r"\$ ", 25)
    spec = CASES[scenario]
    for gid, maximum, refill, mode in spec["budgets"]:
        shell_command(guest, f"budget {gid} {maximum} {refill} {mode}",
                      rf"budget: group {gid} configured")
    if scenario != "independent":
        gid = spec["gid"]
        shell_command(guest, f"group {gid}", rf"group: using {gid}")
        guest.send(f"relay budgetexp {scenario}")
        result = guest.expect(
            rf"UBEXP case={scenario} event=end [^\n]*refused=[0-9]+\n|"
            r"budgetexperiment: FAIL", 70)
        if result.startswith("budgetexperiment: FAIL"):
            raise AssertionError("guest workload reported failure")
        guest.expect(r"\$ ", 15)
    else:
        for gid in (6, 7):
            shell_command(guest, f"group {gid}", rf"group: using {gid}")
            guest.send(f"relaybg budgetexp independent {gid}")
            guest.expect(rf"UBEXP case=independent event=ready [^\n]*"
                         rf"gid={gid} [^\n]*refused=[0-9]+\n", 20)
        deadline = time.monotonic() + 35
        while True:
            ends = re.findall(r"UBEXP case=independent event=end [^\n]*"
                              r"gid=([67]) [^\n]*refused=[0-9]+\n",
                              guest.output)
            if set(ends) == {"6", "7"}:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"independent groups incomplete: {ends}")
            guest.expect(r"UBEXP case=independent event=[a-z]+ [^\n]*"
                         r"refused=[0-9]+\n",
                         max(0.1, deadline - time.monotonic()))
    if "budgetexperiment: FAIL" in guest.output or "panic:" in guest.output:
        raise AssertionError("guest reported failure or kernel panic")


def collect_one(directory, cpus, scenario):
    log_path = directory / f"cpu{cpus}-{scenario}.serial.log"
    spec = CASES[scenario]
    commands = [f"budget {gid} {maximum} {refill} {mode}"
                for gid, maximum, refill, mode in spec["budgets"]]
    if scenario == "independent":
        commands += ["group 6", "relaybg budgetexp independent 6",
                     "group 7", "relaybg budgetexp independent 7"]
    else:
        commands += [f"group {spec['gid']}", f"relay budgetexp {scenario}"]
    command = f"CPUS={cpus}; " + "; ".join(commands)
    started = time.monotonic()
    guest = None
    status, detail, observations = "FAIL", "not started", []
    try:
        with tempfile.TemporaryDirectory(prefix="undobudget-experiment-image-") as temp:
            image = Path(temp) / "fs.img"
            with contextlib.redirect_stdout(io.StringIO()):
                build_image(image)
            guest = Guest(image, cpus)
            with contextlib.redirect_stdout(io.StringIO()):
                run_guest(guest, scenario)
            observations = parse_observations(guest.output, cpus, scenario,
                                              log_path.name)
            detail = validate(observations, scenario)
            status = "PASS"
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        if guest is not None:
            try:
                observations = parse_observations(guest.output, cpus, scenario,
                                                  log_path.name)
            except Exception as parse_error:
                detail += f"; parser: {parse_error}"
    finally:
        if guest is not None:
            log_path.write_text(guest.output)
            guest.close()
        else:
            log_path.write_text("QEMU did not start; see runs.csv for the error.\n")
    run = {"cpus": cpus, "scenario": scenario, "status": status,
           "detail": detail, "command": command,
           "host_elapsed_seconds": f"{time.monotonic() - started:.3f}",
           "raw_log": log_path.name}
    return run, observations


def write_csv(path, fields, records):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpus", type=int, nargs="+", default=[1, 3])
    parser.add_argument("--cases", nargs="+", choices=CASES,
                        default=list(CASES))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(cpus not in (1, 3) for cpus in args.cpus):
        parser.error("this evaluation supports CPUS=1 and CPUS=3")
    if args.output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.output = Path(tempfile.gettempdir()) / f"undobudget-evaluation-{stamp}"
    args.output.mkdir(parents=True, exist_ok=False)
    print(f"Output: {args.output}", flush=True)
    runs, observations = [], []
    qemu_available = shutil.which("qemu-system-riscv64") is not None
    for cpus in (1, 3):
        for scenario in CASES:
            if cpus not in args.cpus or scenario not in args.cases or not qemu_available:
                reason = ("QEMU unavailable" if not qemu_available else
                          "not selected by command")
                runs.append({"cpus": cpus, "scenario": scenario,
                             "status": "MISSING", "detail": reason, "command": "",
                             "host_elapsed_seconds": "", "raw_log": ""})
                continue
            run, rows = collect_one(args.output, cpus, scenario)
            runs.append(run)
            observations.extend(rows)
            write_csv(args.output / "runs.csv", RUN_FIELDS, runs)
            write_csv(args.output / "observations.csv", OBSERVATION_FIELDS,
                      observations)
            print(f"{run['status']} CPUS={cpus} {scenario}: {run['detail']}",
                  flush=True)
    write_csv(args.output / "runs.csv", RUN_FIELDS, runs)
    write_csv(args.output / "observations.csv", OBSERVATION_FIELDS,
              observations)
    print(f"Recorded {len(observations)} guest observations in "
          f"{args.output / 'observations.csv'}", flush=True)
    return 1 if any(run["status"] == "FAIL" for run in runs) else 0


if __name__ == "__main__":
    sys.exit(main())
