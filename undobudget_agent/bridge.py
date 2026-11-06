"""Serialized QEMU serial bridge for the existing xv6 ``agentop`` helper.

The bridge starts its own QEMU process with the Makefile's serial options.
Callers supply a disk image; this module never builds or rewrites one. Each
request is validated, then sent as one bounded shell line. The helper's UB1
records are selected by a fresh transport token, never by command echo.
"""

import errno
import math
import os
import pty
import re
import secrets
import select
import subprocess
import threading
import time
from pathlib import Path

from .validation import validate_request


ROOT = Path(__file__).resolve().parents[1]
MAX_COMMAND = 98  # user/sh.c has a 100-byte buffer: command + newline + NUL.
MAX_SERIAL_BYTES = 65536
_PROMPT = re.compile(rb"(?:^|\n)\$ $")
_HEX = re.compile(rb"(?:[0-9a-f]{2})*")
_STAT = re.compile(rb"[0-9]+(?:,[0-9]+){8}")
_ERROR = re.compile(rb"[a-z][a-z0-9_]*")
_SUPPORTED = frozenset({"list_files", "read_file", "delete_file",
                        "get_budget_status"})


class BridgeFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class _PtyQemu:
    def __init__(self, image, kernel, cpus, qemu):
        if cpus < 1:
            raise ValueError("cpus must be positive")
        master, slave = pty.openpty()
        command = [qemu, "-machine", "virt", "-bios", "none",
                   "-kernel", str(kernel), "-m", "128M", "-smp", str(cpus),
                   "-nographic", "-global", "virtio-mmio.force-legacy=false",
                   "-drive", f"file={image},if=none,format=raw,id=x0",
                   "-device", "virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0"]
        try:
            self.proc = subprocess.Popen(command, cwd=ROOT, stdin=slave,
                                         stdout=slave, stderr=slave,
                                         start_new_session=True)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self.master = master

    def poll(self):
        return self.proc.poll()

    def read(self, timeout):
        readable, _, _ = select.select([self.master], [], [], timeout)
        if not readable:
            return None
        try:
            data = os.read(self.master, 4096)
        except OSError as exc:
            if exc.errno == errno.EIO:
                raise BrokenPipeError("QEMU serial PTY closed") from exc
            raise
        if not data:
            raise BrokenPipeError("QEMU serial PTY closed")
        return data

    def write(self, data):
        while data:
            count = os.write(self.master, data)
            if count <= 0:
                raise BrokenPipeError("QEMU serial write failed")
            data = data[count:]

    def close(self):
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
        finally:
            os.close(self.master)


class _FrameParser:
    """Consume fragmented serial lines and keep only matching helper records."""

    def __init__(self, token):
        self.prefix = f"UB1|{token}|".encode("ascii")
        self.pending = b""
        self.stdout = []
        self.status = None
        self.error = None
        self.total = 0

    def feed(self, data):
        self.total += len(data)
        if self.total > MAX_SERIAL_BYTES:
            raise BridgeFailure("output_limit", "serial output exceeded limit")
        self.pending += data.replace(b"\r", b"")
        while b"\n" in self.pending and self.status is None:
            line, self.pending = self.pending.split(b"\n", 1)
            if not line.startswith(self.prefix):
                continue  # boot text, shell echo, or unrelated console output
            record = line[len(self.prefix):]
            if record.startswith((b"ITEM|", b"DATA|")):
                kind, value = record.split(b"|", 1)
                limit = 28 if kind == b"ITEM" else 512
                if len(value) > limit or len(value) % 2 or _HEX.fullmatch(value) is None:
                    raise BridgeFailure("bad_frame", "invalid helper data record")
                self.stdout.append(record.decode("ascii"))
            elif record.startswith(b"STAT|"):
                value = record[5:]
                if len(value) > 188 or _STAT.fullmatch(value) is None:
                    raise BridgeFailure("bad_frame", "invalid budget snapshot record")
                self.stdout.append(record.decode("ascii"))
            elif record == b"END|OK":
                self.status = "ok"
            elif record.startswith(b"END|ERR|") and _ERROR.fullmatch(record[8:]):
                self.status = "error"
                self.error = record[8:].decode("ascii")
            else:
                raise BridgeFailure("bad_frame", "invalid helper terminal record")


class QemuBridge:
    """Own one QEMU serial session; calls are serialized and fail closed.

    ``execute`` accepts the JSON envelope from ``validate_request`` and
    returns request_id, stdout, status, error, and elapsed_time. ``stdout``
    contains matching ITEM/DATA records (hex payloads), without shell echo.
    A timeout or broken serial connection makes the session unusable because
    the guest operation may still have completed.
    """

    def __init__(self, image=None, *, kernel=ROOT / "kernel/kernel", cpus=3,
                 qemu="qemu-system-riscv64", transport=None):
        if image is None and transport is None:
            raise ValueError("a QEMU disk image is required")
        self.image = image
        self.kernel = kernel
        self.cpus = cpus
        self.qemu = qemu
        self._transport = transport
        self._ready = False
        self._dead = False
        self._lock = threading.Lock()
        self._prefix = secrets.token_hex(8)
        self._sequence = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        with self._lock:
            self._invalidate()

    def _invalidate(self):
        self._dead = True
        transport, self._transport = self._transport, None
        if transport is not None:
            try:
                transport.close()
            except OSError:
                pass  # Preserve the original serial failure in execute().

    def _read(self, deadline):
        while True:
            if self._transport.poll() is not None:
                raise BridgeFailure("qemu_exited", "QEMU exited unexpectedly")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeFailure("timeout", "QEMU response timed out; outcome unknown")
            try:
                chunk = self._transport.read(min(remaining, 0.1))
            except (BrokenPipeError, OSError) as exc:
                code = "qemu_exited" if self._transport.poll() is not None else "broken_pipe"
                raise BridgeFailure(code, str(exc)) from exc
            if chunk:
                return chunk

    def _wait_prompt(self, deadline, initial=b""):
        data = initial.replace(b"\r", b"")
        total = len(data)
        while _PROMPT.search(data) is None:
            chunk = self._read(deadline).replace(b"\r", b"")
            total += len(chunk)
            if total > MAX_SERIAL_BYTES:
                raise BridgeFailure("output_limit", "shell prompt not found")
            data = (data + chunk)[-64:]

    def _start(self, deadline):
        if self._ready:
            return
        if self._transport is None:
            try:
                self._transport = _PtyQemu(self.image, self.kernel,
                                           self.cpus, self.qemu)
            except (OSError, ValueError) as exc:
                raise BridgeFailure("startup_failed", str(exc)) from exc
        self._wait_prompt(deadline)
        self._ready = True

    def execute(self, payload, timeout=20):
        started = time.monotonic()
        validated = validate_request(payload)
        if not validated["ok"]:
            return self._result(None, "validation_error", validated["error"],
                                "", started)
        request = validated["request"]
        request_id = request["request_id"]
        tool = request["tool"]
        if tool not in _SUPPORTED:
            return self._result(request_id, "error",
                                {"code": "unsupported_tool"}, "", started)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            return self._result(request_id, "validation_error",
                                {"code": "invalid_timeout"}, "", started)

        deadline = started + timeout
        if not self._lock.acquire(timeout=max(0, deadline - time.monotonic())):
            return self._result(request_id, "timeout",
                                {"code": "queue_timeout"}, "", started)
        try:
            if self._dead:
                return self._result(request_id, "transport_error",
                                    {"code": "session_closed"}, "", started)
            self._sequence += 1
            token = f"{self._prefix}{self._sequence:x}"
            argument = (str(request["arguments"]["gid"])
                        if tool == "get_budget_status"
                        else request["arguments"]["path"])
            command = f"agentop {token} {tool} {argument}"
            if len(command) > MAX_COMMAND:
                return self._result(request_id, "validation_error",
                                    {"code": "command_too_long"}, "", started)

            parser = _FrameParser(token)
            try:
                self._start(deadline)
                self._transport.write((command + "\n").encode("ascii"))
                while parser.status is None:
                    parser.feed(self._read(deadline))
                # The END line precedes process exit; wait before reusing shell.
                self._wait_prompt(deadline, b"\n" + parser.pending)
            except BridgeFailure as exc:
                self._invalidate()
                status = "timeout" if exc.code == "timeout" else "transport_error"
                return self._result(request_id, status,
                                    {"code": exc.code, "message": str(exc)},
                                    "\n".join(parser.stdout), started)
            except (BrokenPipeError, OSError) as exc:
                self._invalidate()
                return self._result(request_id, "transport_error",
                                    {"code": "broken_pipe", "message": str(exc)},
                                    "\n".join(parser.stdout), started)
            return self._result(request_id, parser.status,
                                None if parser.error is None else {"code": parser.error},
                                "\n".join(parser.stdout), started)
        finally:
            self._lock.release()

    @staticmethod
    def _result(request_id, status, error, stdout, started):
        return {"request_id": request_id, "stdout": stdout, "status": status,
                "error": error, "elapsed_time": time.monotonic() - started}
