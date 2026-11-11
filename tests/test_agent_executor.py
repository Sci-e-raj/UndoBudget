"""Request dispatch tests with a mocked, framed guest bridge."""

import json
import unittest

from undobudget_agent.executor import execute_request


def request(tool, arguments=None, request_id="case-1"):
    return json.dumps({"request_id": request_id, "tool": tool,
                       "arguments": {} if arguments is None else arguments})


class MockBridge:
    def __init__(self, status="ok", stdout="", error=None, request_id="case-1"):
        self.reply = {"request_id": request_id, "status": status,
                      "stdout": stdout, "error": error, "elapsed_time": 0.1}
        self.calls = []

    def execute(self, payload, timeout=20):
        self.calls.append((json.loads(payload), timeout))
        return self.reply


class ExecutorTests(unittest.TestCase):
    def test_list_and_read_decode_only_framed_payloads(self):
        bridge = MockBridge(stdout="ITEM|524541444d45\nITEM|666f6f")
        result = execute_request(request("list_files"), bridge)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["verified_guest"])
        self.assertEqual(result["data"]["files"], ["README", "foo"])
        self.assertEqual(bridge.calls[0][0]["arguments"], {"path": "."})

        bridge = MockBridge(stdout="DATA|6865\nDATA|6c6c6f")
        result = execute_request(request("read_file", {"path": "note"}), bridge)
        self.assertEqual(result["data"], {"content_hex": "68656c6c6f",
                                          "size": 5, "content_utf8": "hello"})

    def test_delete_requires_guest_end_ok(self):
        bridge = MockBridge()
        result = execute_request(request("delete_file", {"path": "old"}), bridge)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"], {"deleted": True})
        self.assertTrue(result["verified_guest"])

        bridge = MockBridge(status="error", error={"code": "unlink_failed_budget_possible"})
        result = execute_request(request("delete_file", {"path": "old"}), bridge)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["data"])
        self.assertEqual(result["error"]["code"], "unlink_failed_budget_possible")

    def test_budget_snapshot_exact_fields_and_gid(self):
        bridge = MockBridge(stdout="STAT|1,1,988,1000,100,0,1,0,0")
        result = execute_request(request("get_budget_status", {"gid": 1}), bridge)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["remaining"], 988)
        self.assertEqual(result["data"]["n_allowed"], 1)
        self.assertEqual(bridge.calls[0][0]["arguments"], {"gid": 1})

        for value in ("STAT|2,1,988,1000,100,0,1,0,0",
                      "STAT|1,1,1001,1000,100,0,1,0,0",
                      "STAT|1,1,988,1000,100,0,1,0",
                      "STAT|1,1,-1,1000,100,0,1,0,0"):
            with self.subTest(value=value):
                result = execute_request(request("get_budget_status", {"gid": 1}),
                                         MockBridge(stdout=value))
                self.assertEqual(result["status"], "protocol_error")
                self.assertFalse(result["verified_guest"])

    def test_write_and_execute_require_guest_success(self):
        bridge = MockBridge()
        result = execute_request(request("write_file", {"path": "note", "content": "hi"}), bridge)
        self.assertEqual(result["data"], {"written": 2})
        self.assertTrue(result["verified_guest"])
        bridge = MockBridge(stdout="DATA|6869")
        result = execute_request(request("execute_program", {"program": "hello"}), bridge)
        self.assertEqual(result["data"]["output_utf8"], "hi")
        self.assertTrue(result["verified_guest"])

    def test_invalid_never_reaches_guest(self):
        bridge = MockBridge()
        invalid = execute_request(request("read_file", {"path": "../secret"}), bridge)
        self.assertEqual(invalid["status"], "validation_error")
        self.assertFalse(invalid["verified_guest"])
        self.assertEqual(bridge.calls, [])

    def test_console_text_or_transport_failure_cannot_claim_success(self):
        bridge = MockBridge(stdout="hello: PASS")
        result = execute_request(request("read_file", {"path": "README"}), bridge)
        self.assertEqual(result["status"], "protocol_error")
        self.assertIsNone(result["data"])

        bridge = MockBridge(status="timeout", error={"code": "timeout"})
        result = execute_request(request("delete_file", {"path": "old"}), bridge)
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["verified_guest"])
        self.assertIsNone(result["data"])

        bridge = MockBridge(request_id="wrong")
        result = execute_request(request("delete_file", {"path": "old"}), bridge)
        self.assertEqual(result["status"], "protocol_error")


if __name__ == "__main__":
    unittest.main()
