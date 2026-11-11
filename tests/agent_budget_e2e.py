#!/usr/bin/env python3
"""Agent/kernel unlink budget tests on fresh, disposable xv6 images.

Run from the repository root: python3 tests/agent_budget_e2e.py
The JSON report path is printed at the end. No production image is changed.
"""

import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from blockstress import build_image
from undobudget_agent.bridge import QemuBridge
from undobudget_agent.executor import execute_request
from undobudget_agent.validation import validate_request


# Approved P01 policy, also checked against the current kernel constant.
UNLINK_COST = 12
SHELL_PROMPT = re.compile(rb"\n\$ $")


class Session:
    def __init__(self, bridge, cpus, records):
        self.bridge = bridge
        self.cpus = cpus
        self.records = records
        self.serial = 0
        self.selected_gid = 1

    def shell(self, command, expected=None):
        # Fixed test setup commands only. Agent JSON never reaches this path.
        deadline = time.monotonic() + 25
        with self.bridge._lock:
            self.bridge._start(deadline)
            self.bridge._transport.write((command + "\n").encode("ascii"))
            output = b""
            while SHELL_PROMPT.search(output) is None:
                try:
                    output += self.bridge._read(deadline).replace(b"\r", b"")
                except Exception as exc:
                    raise AssertionError(f"{command!r}: {exc}; serial={output[-1000:]!r}") from exc
                if len(output) > 16384:
                    raise AssertionError("shell setup output exceeded limit")
        text = output.decode("utf-8", "replace")
        if expected is not None and expected not in text:
            raise AssertionError(f"{command!r} did not report {expected!r}: {text!r}")
        if "panic:" in text or "FAIL" in text or "failed" in text:
            raise AssertionError(f"shell setup failed: {text!r}")
        if command.startswith("group "):
            self.selected_gid = int(command.split()[1])
        return text

    def request(self, scenario, tool, arguments, gid, timeout=20):
        self.serial += 1
        payload = json.dumps({"request_id": f"e2e-{self.cpus}-{self.serial}",
                              "tool": tool, "arguments": arguments},
                             separators=(",", ":"))
        validated = validate_request(payload)
        assert validated["ok"], validated
        # Query snapshots from the default group so the act of launching a
        # read-only helper does not spend the group being observed.
        previous_gid = self.selected_gid
        if tool == "get_budget_status" and previous_gid != 1:
            self.shell("group 1", "group: using 1")
        try:
            executing_gid = self.selected_gid
            result = execute_request(payload, self.bridge, timeout=timeout)
        finally:
            if self.selected_gid != previous_gid:
                self.shell(f"group {previous_gid}",
                           f"group: using {previous_gid}")

        if tool == "get_budget_status":
            remaining = (result["data"]["remaining"] if result["status"] == "ok"
                         else None)
            kernel_result = (0 if result["status"] == "ok" else
                             -1 if result["status"] == "error" else None)
            operation = f"budgetstat({arguments['gid']}, &snapshot)"
        else:
            # This is a separate framed observation, not an inferred balance.
            if result["verified_guest"]:
                balance = self.request(scenario + ":balance", "get_budget_status",
                                       {"gid": gid}, gid)
                assert balance["status"] == "ok" and balance["verified_guest"]
                remaining = balance["data"]["remaining"]
            else:
                remaining = None
            if tool == "delete_file":
                # agentop calls unlink exactly once after its file preflight.
                kernel_result = (0 if result["status"] == "ok" else
                                 -1 if result["status"] == "error" and
                                 result["error"]["code"] ==
                                 "unlink_failed_budget_possible" else None)
                operation = f"unlink({arguments['path']})"
            else:
                # The helper verifies the completed read but does not expose
                # the individual read() return values or opened fd.
                if result["status"] == "ok":
                    kernel_result = {"open": "succeeded", "fstat": 0,
                                     "total_read_bytes": result["data"]["size"]}
                elif (result["status"] == "error" and
                      result["error"]["code"] == "open_failed"):
                    kernel_result = {"open": -1}
                else:
                    kernel_result = None
                operation = f"open/fstat/read({arguments['path']})"

        self.records.append({
            "scenario": scenario, "cpus": self.cpus, "gid": gid,
            "executing_gid": executing_gid,
            "original_json": payload,
            "validated_arguments": validated["request"]["arguments"],
            "guest_operation": operation,
            "kernel_result": kernel_result,
            "remaining_budget": remaining,
            "elapsed_time": result["elapsed_time"],
            "agent_visible_result": result,
        })
        return result

    def snapshot(self, scenario, gid):
        result = self.request(scenario, "get_budget_status", {"gid": gid}, gid)
        assert result["status"] == "ok" and result["verified_guest"], result
        return result["data"]

    def exists(self, scenario, path, gid):
        previous_gid = self.selected_gid
        if previous_gid != 1:
            self.shell("group 1", "group: using 1")
        try:
            result = self.request(scenario, "read_file", {"path": path}, gid)
        finally:
            if self.selected_gid != previous_gid:
                self.shell(f"group {previous_gid}",
                           f"group: using {previous_gid}")
        assert result["verified_guest"], result
        if result["status"] == "ok":
            return True
        assert result["status"] == "error" and result["error"]["code"] == "open_failed", result
        return False

    def delete(self, scenario, path, gid, allowed, timeout=20):
        before = self.snapshot(scenario + ":before", gid)
        result = self.request(scenario, "delete_file", {"path": path}, gid,
                              timeout=timeout)
        assert result["verified_guest"], result
        after = self.snapshot(scenario + ":after", gid)
        if allowed:
            assert result["status"] == "ok" and result["verified_guest"], result
            assert result["data"] == {"deleted": True}
            assert after["n_allowed"] == before["n_allowed"] + 2
            assert not self.exists(scenario + ":absent", path, gid)
        else:
            assert result["status"] == "error" and result["verified_guest"], result
            assert result["error"]["code"] == "unlink_failed_budget_possible"
            assert after["n_allowed"] == before["n_allowed"] + 1
            assert after["n_refused"] == before["n_refused"] + 1
            assert self.exists(scenario + ":survives", path, gid)
        assert after["configured"] == 1 and 0 <= after["remaining"] <= after["max"]
        return result, before, after


def exercise(bridge, cpus, records):
    session = Session(bridge, cpus, records)
    # All fixtures are created while the shell still selects group 1, before
    # any of the tested groups performs an unlink.
    fixtures = ("as0", "af0", "af1", "ab0", "ab1", "ak0", "ai0", "ai1", "ai2")
    for path in fixtures:
        session.shell(f"echo x > {path}")
    for gid, maximum, refill, mode in (
            (2, 2 * UNLINK_COST + 3 * 4, 0, "fail"),
            (3, UNLINK_COST + 4 * 4, 0, "fail"),
            (4, UNLINK_COST + 4, UNLINK_COST, "block"),
            (5, UNLINK_COST + 2 * 4, 0, "fail"),
            (6, UNLINK_COST + 4, 0, "fail")):
        session.shell(f"budget {gid} {maximum} {refill} {mode}",
                      f"budget: group {gid} configured")
        state = session.snapshot(f"configured-{gid}", gid)
        assert (state["max"], state["remaining"], state["refill_per_100_ticks"],
                state["mode"]) == (maximum, maximum, refill, 1 if mode == "block" else 0)

    session.shell("group 2", "group: using 2")
    _, before, after = session.delete("successful-delete", "as0", 2, True)
    assert before["remaining"] == 2 * UNLINK_COST + 3 * 4
    assert after["remaining"] == UNLINK_COST + 2 * 4
    session.delete("fail-last-allowed", "af0", 2, True)
    _, before, after = session.delete("fail-exhausted", "af1", 2, False)
    assert before["remaining"] == 4 and after["remaining"] == 0

    session.shell("group 3", "group: using 3")
    before = session.snapshot("fork-before", 3)
    session.shell("relay budgettest shared", "budgettest: PASS shared")
    after = session.snapshot("fork-after", 3)
    assert after["n_allowed"] == before["n_allowed"] + 4
    assert after["n_refused"] == before["n_refused"] + 1
    assert after["remaining"] == 4
    assert not session.exists("fork-child-removed", "bsc", 3)
    assert session.exists("fork-parent-survived", "bsp", 3)
    _, before, after = session.delete("fork-shared-budget", "ak0", 3, False)
    assert before["remaining"] == 4 and after["remaining"] == 0

    session.shell("group 4", "group: using 4")
    session.delete("block-exhaust", "ab0", 4, True)
    _, before, after = session.delete("block-refill-success", "ab1", 4, True,
                                      timeout=25)
    assert after["n_blocked"] > before["n_blocked"], (before, after)

    session.shell("group 5", "group: using 5")
    session.delete("independent-first", "ai0", 5, True)
    first = session.snapshot("first-exhausted", 5)
    assert first["remaining"] == 4
    session.shell("group 6", "group: using 6")
    second = session.snapshot("second-untouched", 6)
    assert second["remaining"] == UNLINK_COST + 4 and second["n_allowed"] == 0
    session.delete("independent-second", "ai1", 6, True)
    assert session.snapshot("first-still-exhausted", 5)["remaining"] == 4
    session.shell("group 5", "group: using 5")
    session.delete("independent-refusal", "ai2", 5, False)
    assert session.snapshot("second-still-independent", 6)["n_refused"] == 0


def main():
    source = (ROOT / "kernel/sysfile.c").read_text()
    assert re.search(r"^#define\s+UNLINK_COST\s+12$", source, re.MULTILINE), \
        "kernel unlink cost differs from the approved 12-point policy"
    records = []
    cpus_to_test = [int(value) for value in sys.argv[1:]] or [1, 3]
    assert all(value in (1, 3) for value in cpus_to_test)
    with tempfile.NamedTemporaryFile(mode="w", prefix="undobudget-agent-budget-",
                                     suffix=".json", delete=False) as report:
        report_path = Path(report.name)
    try:
        with tempfile.TemporaryDirectory(prefix="undobudget-agent-budget-img-") as directory:
            for cpus in cpus_to_test:
                image = Path(directory) / f"fs-{cpus}.img"
                build_image(image)
                with QemuBridge(image, cpus=cpus) as bridge:
                    exercise(bridge, cpus, records)
                print(f"agent budget: PASS CPUS={cpus}", flush=True)
    finally:
        report_path.write_text(json.dumps(records, indent=2) + "\n")
        print(f"request evidence: {report_path} ({len(records)} records)", flush=True)


if __name__ == "__main__":
    main()
