#!/usr/bin/env python3
"""Run groupauth's trusted administrator branch in a disposable xv6 copy.

The production init and repository fs.img are never modified. The copied init
execs groupauth once after configuring groups 0 and 1, before starting sh.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import blockstress


ROOT = Path(__file__).resolve().parents[1]
MARKER = "  dup(0); // stderr\n"
BOOT_TEST = """
  int authpid = fork();
  if (authpid == 0) {
    char *authargs[] = {"groupauth", "admin", 0};
    exec("groupauth", authargs);
    exit(1);
  }
  int authstatus = -1;
  if (wait(&authstatus) != authpid || authstatus != 0)
    exit(1);
"""


def main():
    cpus = int(sys.argv[1]) if len(sys.argv) == 2 else 1
    if cpus not in (1, 3):
        raise ValueError("CPUS must be 1 or 3")
    with tempfile.TemporaryDirectory(prefix="undobudget-admin-boot-") as temp:
        copy = Path(temp) / "source"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(
            ".git", "fs.img", "test-xv6.out", "__pycache__"))
        init = copy / "user/init.c"
        source = init.read_text()
        if source.count(MARKER) != 1:
            raise AssertionError("init startup marker changed")
        init.write_text(source.replace(MARKER, MARKER + BOOT_TEST))

        blockstress.ROOT = copy
        image = Path(temp) / "fresh.img"
        blockstress.build_image(image)
        guest = blockstress.Guest(image, cpus)
        try:
            guest.expect(r"groupauth: PASS\n", 30)
            guest.expect(r"\$ ", 20)
            if "groupauth: FAIL" in guest.output or "panic:" in guest.output:
                raise AssertionError("administrator boot test reported failure")
        finally:
            guest.close()
    print(f"admin boot: PASS CPUS={cpus}")


if __name__ == "__main__":
    main()
