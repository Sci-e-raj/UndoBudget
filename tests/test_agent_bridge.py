"""Serial framing and failure tests without starting QEMU."""

import json
import threading
import time
import unittest
from collections import deque

from undobudget_agent.bridge import QemuBridge


def request(tool="list_files", path=".", request_id="r1"):
    return json.dumps({"request_id": request_id, "tool": tool,
                       "arguments": {"path": path}})


class FakeStream:
    def __init__(self, on_write=None, boot=True):
        self.chunks = deque([b"\r\ninit: starting sh\r\n$ "] if boot else [])
        self.writes = []
        self.on_write = on_write
        self.closed = False
        self.exit_code = None
        self.broken = False

    def poll(self):
        return self.exit_code

    def read(self, timeout):
        if self.broken:
            raise BrokenPipeError("fake serial closed")
        if self.chunks:
            return self.chunks.popleft()
        time.sleep(min(timeout, 0.005))
        return None

    def write(self, data):
        self.writes.append(data)
        if self.on_write:
            self.on_write(self, data)

    def close(self):
        self.closed = True


def framed(stream, command, payload=b"ITEM|666f6f"):
    token = command.decode("ascii").split()[1]
    stream.chunks.extend([
        command + b"\r\nUB1|wrong|END|OK\r\n",
        f"UB1|{token}|".encode()[:8],
        f"UB1|{token}|".encode()[8:] + payload + b"\r\n",
        f"UB1|{token}|END|OK\r\n$ ".encode(),
    ])


class BridgeTests(unittest.TestCase):
    def test_fragmented_frame_ignores_echo_and_wrong_token(self):
        stream = FakeStream(framed)
        with QemuBridge(transport=stream) as bridge:
            result = bridge.execute(request())
        self.assertEqual(result["request_id"], "r1")
        self.assertEqual(result["stdout"], "ITEM|666f6f")
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["error"])
        self.assertGreaterEqual(result["elapsed_time"], 0)
        self.assertEqual(len(stream.writes), 1)
        self.assertTrue(stream.closed)

    def test_guest_error_is_distinct_from_transport_error(self):
        def fail(stream, command):
            token = command.decode().split()[1]
            stream.chunks.append(f"UB1|{token}|END|ERR|open_failed\r\n$ ".encode())

        with QemuBridge(transport=FakeStream(fail)) as bridge:
            result = bridge.execute(request("read_file", "missing"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], {"code": "open_failed"})
        self.assertEqual(result["stdout"], "")

    def test_timeout_closes_session_without_retry(self):
        stream = FakeStream()
        bridge = QemuBridge(transport=stream)
        result = bridge.execute(request(), timeout=0.02)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["error"]["code"], "timeout")
        self.assertTrue(stream.closed)
        self.assertEqual(bridge.execute(request())["error"]["code"],
                         "session_closed")
        self.assertEqual(len(stream.writes), 1)

    def test_startup_timeout_and_exit(self):
        bridge = QemuBridge(transport=FakeStream(boot=False))
        self.assertEqual(bridge.execute(request(), timeout=0.02)["status"],
                         "timeout")

        def exit_guest(stream, _):
            stream.exit_code = 1

        bridge = QemuBridge(transport=FakeStream(exit_guest))
        result = bridge.execute(request())
        self.assertEqual(result["status"], "transport_error")
        self.assertEqual(result["error"]["code"], "qemu_exited")

        bridge = QemuBridge("/tmp/unused.img", qemu="no-such-qemu-binary")
        self.assertEqual(bridge.execute(request())["error"]["code"],
                         "startup_failed")

    def test_broken_pipe_and_bad_frame(self):
        def break_pipe(stream, _):
            stream.broken = True

        bridge = QemuBridge(transport=FakeStream(break_pipe))
        self.assertEqual(bridge.execute(request())["error"]["code"],
                         "broken_pipe")

        def bad_frame(stream, command):
            token = command.decode().split()[1]
            stream.chunks.append(f"UB1|{token}|END|MAYBE\n".encode())

        bridge = QemuBridge(transport=FakeStream(bad_frame))
        self.assertEqual(bridge.execute(request())["error"]["code"],
                         "bad_frame")

    def test_validation_and_unsupported_tools_send_nothing(self):
        stream = FakeStream()
        bridge = QemuBridge(transport=stream)
        self.assertEqual(bridge.execute(request("read_file", "../bad"))["status"],
                         "validation_error")
        self.assertEqual(bridge.execute(request("write_file", "note"))["status"],
                         "validation_error")  # missing content
        write_request = json.dumps({"request_id": "r2", "tool": "write_file",
                                    "arguments": {"path": "note", "content": "hi"}})
        self.assertEqual(bridge.execute(write_request)["error"],
                         {"code": "unsupported_tool"})
        self.assertEqual(bridge.execute(request(), timeout=0)["error"],
                         {"code": "invalid_timeout"})
        long_path = "/".join(["a" * 14] * 7)
        self.assertEqual(bridge.execute(request("read_file", long_path))["error"],
                         {"code": "command_too_long"})
        self.assertEqual(stream.writes, [])

    def test_concurrent_calls_are_serialized_with_distinct_tokens(self):
        release_first = threading.Event()
        first_written = threading.Event()

        class DelayedStream(FakeStream):
            def write(self, data):
                super().write(data)
                first_written.set()

            def read(self, timeout):
                if len(self.writes) == 1 and not release_first.is_set():
                    time.sleep(min(timeout, 0.005))
                    return None
                return super().read(timeout)

        stream = DelayedStream(framed)
        bridge = QemuBridge(transport=stream)
        results = []

        def call(index):
            results.append(bridge.execute(request(request_id=f"r{index}")))

        threads = [threading.Thread(target=call, args=(i,)) for i in (1, 2)]
        threads[0].start()
        self.assertTrue(first_written.wait(timeout=1))
        threads[1].start()
        time.sleep(0.02)
        self.assertEqual(len(stream.writes), 1)
        release_first.set()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        bridge.close()
        self.assertEqual({result["request_id"] for result in results}, {"r1", "r2"})
        self.assertTrue(all(result["status"] == "ok" for result in results))
        tokens = [command.decode().split()[1] for command in stream.writes]
        self.assertEqual(len(set(tokens)), 2)

    def test_queued_request_times_out_without_closing_active_session(self):
        release = threading.Event()
        written = threading.Event()

        class SlowStream(FakeStream):
            def write(self, data):
                super().write(data)
                written.set()

            def read(self, timeout):
                if self.writes and not release.is_set():
                    time.sleep(min(timeout, 0.005))
                    return None
                return super().read(timeout)

        stream = SlowStream(framed)
        bridge = QemuBridge(transport=stream)
        first = []
        thread = threading.Thread(target=lambda: first.append(bridge.execute(request(), timeout=1)))
        thread.start()
        self.assertTrue(written.wait(timeout=1))
        queued = bridge.execute(request(request_id="r2"), timeout=0.02)
        self.assertEqual(queued["status"], "timeout")
        self.assertEqual(queued["error"], {"code": "queue_timeout"})
        self.assertFalse(stream.closed)
        self.assertEqual(len(stream.writes), 1)
        release.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(first[0]["status"], "ok")
        bridge.close()


if __name__ == "__main__":
    unittest.main()
