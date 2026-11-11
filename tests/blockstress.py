#!/usr/bin/env python3
"""Build a scratch xv6 image and exercise BLOCK budgets on 1 and 3 CPUs.

Run from the repository root: python3 tests/blockstress.py
The repository's fs.img is never opened or replaced.
"""

import os
import pty
import re
import select
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_image(path):
    subprocess.run(["make", "-j2"], cwd=ROOT, check=True)
    dry = subprocess.check_output(["make", "-n", "-B", "fs.img"], cwd=ROOT, text=True)
    line = next(line for line in dry.splitlines()
                if line.startswith("mkfs/mkfs fs.img "))
    mkfs, _, *inputs = shlex.split(line)
    subprocess.run(["make", "-j2", mkfs, *inputs[1:]], cwd=ROOT, check=True)
    subprocess.run([str(ROOT / mkfs), str(path), *inputs], cwd=ROOT, check=True)


class Guest:
    def __init__(self, image, cpus):
        master, slave = pty.openpty()
        self.master = master
        self.output = ""
        self.cursor = 0
        self.proc = subprocess.Popen(
            ["qemu-system-riscv64", "-machine", "virt", "-bios", "none",
             "-kernel", "kernel/kernel", "-m", "128M", "-smp", str(cpus),
             "-nographic", "-global", "virtio-mmio.force-legacy=false",
             "-drive", f"file={image},if=none,format=raw,id=x0",
             "-device", "virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0"],
            cwd=ROOT, stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True,
        )
        os.close(slave)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        os.close(self.master)

    def send(self, command):
        print(f"> {command}", flush=True)
        os.write(self.master, (command + "\n").encode())

    def expect(self, pattern, timeout):
        deadline = time.monotonic() + timeout
        while True:
            match = re.search(pattern, self.output[self.cursor:])
            if match:
                self.cursor += match.end()
                return match.group()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {pattern!r}")
            readable, _, _ = select.select([self.master], [], [], remaining)
            if not readable:
                continue
            try:
                chunk = os.read(self.master, 4096).decode(errors="replace")
            except OSError as error:
                raise RuntimeError("QEMU closed before expected result") from error
            if not chunk:
                raise RuntimeError("QEMU exited before expected result")
            chunk = chunk.replace("\r", "")
            self.output += chunk
            sys.stdout.write(chunk)
            sys.stdout.flush()
            if "blockstress: FAIL:" in self.output or "panic:" in self.output:
                raise AssertionError("xv6 reported a test failure or kernel panic")

    def command(self, command, pattern, timeout=10):
        self.send(command)
        return self.expect(pattern, timeout)


def exercise_independent(guest):
    for gid in (8, 9):
        guest.command(f"budget {gid} 12 3 block",
                      rf"budget: group {gid} configured")
    guest.command("group 8", r"group: using 8")
    guest.command("relaybg blockstress independent 8",
                  r"blockstress: READY independent 8")
    guest.command("group 9", r"group: using 9")
    guest.command("relaybg blockstress independent 9",
                  r"blockstress: READY independent 9")
    passed = set()
    deadline = time.monotonic() + 50
    while passed != {"8", "9"}:
        result = guest.expect(r"blockstress: PASS independent [89]",
                              max(0.1, deadline - time.monotonic()))
        passed.add(result[-1])


def exercise(guest):
    guest.expect(r"\$ ", 20)
    cases = [
        (2, "8 3 block", "refill", 45),
        (3, "20 12 block", "contend", 75),
        (4, "24 3 block", "insufficient", 85),
        (5, "24 0 block", "zero", 15),
        (6, "24 1 block", "killed", 20),
        (7, "24 0 block", "reconfigure", 30),
    ]
    for gid, budget, mode, timeout in cases:
        guest.command(f"budget {gid} {budget}",
                      rf"budget: group {gid} configured")
        if gid == 7:
            guest.command("budget 7 120 120 block",
                          r"budget: group 7 could not be configured")
        guest.command(f"group {gid}", rf"group: using {gid}")
        guest.command(f"relay blockstress {mode}",
                      rf"blockstress: PASS {mode}", timeout)
    exercise_independent(guest)


def main():
    cpus = [int(arg) for arg in sys.argv[1:]] or [1, 3]
    with tempfile.TemporaryDirectory(prefix="undobudget-blockstress-") as temp:
        for count in cpus:
            image = Path(temp) / f"fs-{count}.img"
            build_image(image)
            guest = Guest(image, count)
            try:
                print(f"\n=== CPUS={count} ===", flush=True)
                exercise(guest)
                print(f"BLOCKSTRESS PASS CPUS={count}", flush=True)
            except Exception:
                print(f"\nBLOCKSTRESS FAIL CPUS={count}; last guest output:\n"
                      f"{guest.output[-2000:]}", file=sys.stderr)
                raise
            finally:
                guest.close()


if __name__ == "__main__":
    main()
