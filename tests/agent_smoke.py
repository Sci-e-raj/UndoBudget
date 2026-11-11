#!/usr/bin/env python3
"""Smoke-test every supported agent tool on a disposable xv6 image."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blockstress import build_image
from undobudget_agent.bridge import QemuBridge
from undobudget_agent.executor import execute_request


def call(bridge, request_id, tool, arguments):
    payload = json.dumps({"request_id": request_id, "tool": tool,
                          "arguments": arguments})
    result = execute_request(payload, bridge, timeout=20)
    print(request_id, tool, result["status"], result["error"])
    return result


def main():
    with tempfile.TemporaryDirectory(prefix="undobudget-agent-smoke-") as directory:
        image = Path(directory) / "fs.img"
        build_image(image)
        with QemuBridge(image) as bridge:
            listing = call(bridge, "smoke-list", "list_files", {})
            assert listing["status"] == "ok" and listing["verified_guest"]
            assert "README" in listing["data"]["files"]

            content = call(bridge, "smoke-read", "read_file", {"path": "README"})
            assert content["status"] == "ok" and content["verified_guest"]
            assert content["data"]["size"] > 0

            note = "hello from agent " * 6 + "🌍"
            written = call(bridge, "smoke-write", "write_file",
                           {"path": "agent_note", "content": note})
            assert written["status"] == "ok" and written["verified_guest"]
            assert written["data"] == {"written": len(note.encode("utf-8"))}
            reread = call(bridge, "smoke-reread", "read_file",
                          {"path": "agent_note"})
            assert reread["status"] == "ok" and reread["verified_guest"]
            assert reread["data"]["content_utf8"] == note

            executed = call(bridge, "smoke-execute", "execute_program",
                            {"program": "hello"})
            assert executed["status"] == "ok" and executed["verified_guest"]
            assert "hello: PASS" in executed["data"]["output_utf8"]
            listed = call(bridge, "smoke-execute-ls", "execute_program",
                          {"program": "ls"})
            assert listed["status"] == "ok" and listed["verified_guest"]
            assert "agent_note" in listed["data"]["output_utf8"]
            table = call(bridge, "smoke-execute-budgetstat", "execute_program",
                         {"program": "budgetstat"})
            assert table["status"] == "ok" and table["verified_guest"]
            assert "REMAINING/MAX" in table["data"]["output_utf8"]

            before = call(bridge, "smoke-stat-before", "get_budget_status",
                          {"gid": 1})
            assert before["status"] == "ok" and before["verified_guest"]
            assert before["data"]["gid"] == 1 and before["data"]["configured"] == 1

            admin_before = call(bridge, "smoke-admin-before", "get_budget_status",
                                {"gid": 0})
            admin_after = call(bridge, "smoke-admin-after", "get_budget_status",
                               {"gid": 0})
            assert admin_before["status"] == admin_after["status"] == "ok"
            assert admin_after["data"]["n_allowed"] > admin_before["data"]["n_allowed"]

            unused = call(bridge, "smoke-stat-unused", "get_budget_status",
                          {"gid": 14})
            assert unused["status"] == "ok" and unused["verified_guest"]
            assert unused["data"]["configured"] == 0
            assert unused["data"]["remaining"] == unused["data"]["max"] == 0

            deleted = call(bridge, "smoke-delete", "delete_file", {"path": "README"})
            assert deleted["status"] == "ok" and deleted["verified_guest"]
            assert deleted["data"] == {"deleted": True}

            after = call(bridge, "smoke-stat-after", "get_budget_status",
                         {"gid": 1})
            assert after["status"] == "ok" and after["verified_guest"]
            # Four intervening helpers and the final snapshot each pay an
            # exec charge; unlink adds one more deduction.
            assert after["data"]["n_allowed"] == before["data"]["n_allowed"] + 6

            missing = call(bridge, "smoke-missing", "read_file", {"path": "README"})
            assert missing["status"] == "error" and missing["verified_guest"]
            assert missing["error"]["code"] == "open_failed"

        print("agent smoke: PASS (all 6 supported tools)")


if __name__ == "__main__":
    main()
