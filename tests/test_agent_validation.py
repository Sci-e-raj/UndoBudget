import json
import subprocess
import unittest
from unittest.mock import patch

from undobudget_agent import (
    ALLOWED_TOOLS,
    MAX_CONTENT_BYTES,
    MAX_PATH_BYTES,
    validate_request,
)


def request(tool, arguments=None, request_id="req-1"):
    return json.dumps({"request_id": request_id, "tool": tool,
                       "arguments": {} if arguments is None else arguments})


class ValidatorTests(unittest.TestCase):
    def assert_error(self, payload, code, field):
        result = validate_request(payload)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], code)
        self.assertEqual(result["error"]["field"], field)
        self.assertIsInstance(result["error"]["message"], str)
        self.assertTrue(result["error"]["message"])

    def test_all_allowlisted_tools(self):
        cases = {
            "list_files": {},
            "read_file": {"path": "notes.txt"},
            "delete_file": {"path": "old/log"},
            "write_file": {"path": "new.txt", "content": "hello"},
            "execute_program": {"program": "hello"},
            "get_budget_status": {"gid": 0},
        }
        self.assertEqual(set(cases), ALLOWED_TOOLS)
        for tool, arguments in cases.items():
            with self.subTest(tool=tool):
                result = validate_request(request(tool, arguments).encode())
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["request"]["request_id"], "req-1")
                self.assertEqual(result["request"]["tool"], tool)
                self.assertEqual(result["request"]["arguments"],
                                 {"path": "."} if tool == "list_files" else arguments)

    def test_list_files_path_policy(self):
        for path in (".", "logs", "logs/2026", "_data/a-b.txt"):
            with self.subTest(path=path):
                result = validate_request(request("list_files", {"path": path}))
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["request"]["arguments"]["path"], path)
        self.assert_error(request("read_file", {"path": "."}),
                          "invalid_path", "$.arguments.path")

    def test_relative_and_traversal_edges(self):
        invalid = (
            "", "/", "/etc/passwd", "../secret", "a/../secret", "a/..",
            "./a", "a/./b", "a//b", "a/", "a\\..\\b", "C:/boot",
            "a;rm", "a\nb", "a b", "-option", ".hidden", "a" * 15,
            "a" * (MAX_PATH_BYTES + 1),
        )
        for path in invalid:
            with self.subTest(path=path):
                self.assert_error(request("delete_file", {"path": path}),
                                  "invalid_path", "$.arguments.path")
        self.assertTrue(validate_request(request("read_file", {"path": "a" * 14}))["ok"])

    def test_non_string_paths(self):
        for path in (None, 0, False, ["a"], {"name": "a"}):
            with self.subTest(path=path):
                self.assert_error(request("read_file", {"path": path}),
                                  "invalid_type", "$.arguments.path")

    def test_content_utf8_byte_bound_and_type(self):
        accepted = ("", "x" * MAX_CONTENT_BYTES, "é" * (MAX_CONTENT_BYTES // 2),
                    "line 1\nline 2; $(not executed)")
        for content in accepted:
            with self.subTest(length=len(content)):
                result = validate_request(request("write_file",
                                                  {"path": "note", "content": content}))
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["request"]["arguments"]["content"], content)
        for content in ("x" * (MAX_CONTENT_BYTES + 1), "é" * 2049):
            with self.subTest(length=len(content)):
                self.assert_error(request("write_file", {"path": "note",
                                                         "content": content}),
                                  "too_large", "$.arguments.content")
        for content in (None, 5, False, ["text"]):
            with self.subTest(content=content):
                self.assert_error(request("write_file", {"path": "note",
                                                         "content": content}),
                                  "invalid_type", "$.arguments.content")
        self.assert_error(request("write_file", {"path": "note", "content": "a\x00b"}),
                          "invalid_value", "$.arguments.content")
        self.assert_error(request("write_file", {"path": "note",
                                                  "content": "\ud800"}),
                          "invalid_value", "$.arguments.content")

    def test_program_is_allowlisted_and_never_executed(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("executed")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("executed")):
            self.assertTrue(validate_request(request("execute_program",
                                                     {"program": "hello"}))["ok"])
            for program in ("sh", "rm", "forktest", "hello; rm x",
                            "/bin/hello", "../hello"):
                with self.subTest(program=program):
                    self.assert_error(request("execute_program", {"program": program}),
                                      "unsupported_program", "$.arguments.program")
        self.assert_error(request("execute_program", {"program": "hello",
                                                       "argv": [";rm"]}),
                          "unexpected_field", "$.arguments.argv")
        self.assert_error(request("execute_program", {"program": 1}),
                          "invalid_type", "$.arguments.program")

    def test_gid_exact_integer_and_bounds(self):
        for gid in (0, 15):
            self.assertTrue(validate_request(request("get_budget_status",
                                                     {"gid": gid}))["ok"])
        for gid in (-1, 16, 999999):
            with self.subTest(gid=gid):
                self.assert_error(request("get_budget_status", {"gid": gid}),
                                  "invalid_value", "$.arguments.gid")
        for gid in (True, False, "1", 1.0, None):
            with self.subTest(gid=gid):
                self.assert_error(request("get_budget_status", {"gid": gid}),
                                  "invalid_type", "$.arguments.gid")

    def test_missing_and_unknown_fields(self):
        self.assert_error('{}', "missing_field", "$.arguments")
        self.assert_error(request("write_file", {"path": "note"}),
                          "missing_field", "$.arguments.content")
        self.assert_error(request("read_file", {"path": "note", "mode": "all"}),
                          "unexpected_field", "$.arguments.mode")
        self.assert_error(json.dumps({"request_id": "r", "tool": "list_files",
                                      "arguments": {}, "command": "rm x"}),
                          "unexpected_field", "$.command")
        self.assert_error(request("shell", {"command": "rm x"}),
                          "unsupported_tool", "$.tool")

    def test_json_shape_types_and_duplicates(self):
        self.assert_error("[1,2]", "invalid_shape", "$")
        self.assert_error("{", "invalid_json", "$")
        self.assert_error('{"request_id":"a","request_id":"b",'
                          '"tool":"list_files","arguments":{}}',
                          "duplicate_key", "$")
        self.assert_error('{"request_id":"a","tool":"list_files",'
                          '"arguments":{"path":".","path":"x"}}',
                          "duplicate_key", "$")
        self.assert_error('{"request_id":"a","tool":"get_budget_status",'
                          '"arguments":{"gid":NaN}}', "invalid_json", "$")
        self.assert_error(b"\xff", "invalid_json", "$")
        self.assert_error({"tool": "list_files"}, "invalid_type", "$")
        self.assert_error(" " * 32769, "too_large", "$")
        self.assert_error(request("list_files", []) , "invalid_type", "$.arguments")

    def test_request_id_is_bounded_safe_token(self):
        for request_id in ("", "a" * 65, "a b", "x;rm"):
            with self.subTest(request_id=request_id):
                self.assert_error(request("list_files", request_id=request_id),
                                  "invalid_value", "$.request_id")
        for request_id in (1, None):
            self.assert_error(request("list_files", request_id=request_id),
                              "invalid_type", "$.request_id")
        self.assertTrue(validate_request(request("list_files", request_id="a" * 64))["ok"])


if __name__ == "__main__":
    unittest.main()
