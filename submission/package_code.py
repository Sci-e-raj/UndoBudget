#!/usr/bin/env python3
"""Package the current source tree, including uncommitted source files.

Run from the repository root: python3 submission/package_code.py
No Git state or filesystem image is modified.
"""

import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).resolve().parent / "UndoBudget_Code.zip"
ROOT_FILES = {
    ".clang-format", ".editorconfig", ".gdbinit.tmpl-riscv", ".gitignore",
    "LICENSE", "Makefile", "README", "PROJECT.md", "test-xv6.py",
    ".github/workflows/test.yml",
}
SUFFIXES = {
    "kernel": {".c", ".h", ".S", ".ld"},
    "user": {".c", ".h", ".S", ".ld", ".pl"},
    "mkfs": {".c"},
    "tests": {".c", ".py"},
    "experiments": {".md", ".py"},
    "undobudget_agent": {".py"},
    "docs": {".md"},
}


def selected(path):
    if path in ROOT_FILES:
        return True
    parts = Path(path).parts
    return (len(parts) >= 2 and parts[0] in SUFFIXES and
            Path(path).suffix in SUFFIXES[parts[0]] and
            path != "user/usys.S")


def main():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    new = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    paths = sorted({name.decode() for name in (tracked + new).split(b"\0")
                    if name and selected(name.decode())})
    if not {"user/consolebudget.c", "user/execbudget.c", "user/fsbudget.c",
            "tests/admin_boot.py"}.issubset(paths):
        raise RuntimeError("a new project source file is missing")
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            source = ROOT / path
            if not source.is_file():
                raise FileNotFoundError(source)
            info = ZipInfo("UndoBudget/" + path, date_time=(2026, 11, 10, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
            info.external_attr = (0o100000 | mode) << 16
            archive.writestr(info, source.read_bytes(), compress_type=ZIP_DEFLATED)
    with ZipFile(OUTPUT) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("ZIP integrity check failed")
    print(f"Wrote {OUTPUT} ({len(paths)} source files)")


if __name__ == "__main__":
    main()
