#!/usr/bin/env python3
"""Inspect creator gid in a stopped xv6 image after creatorprobe runs.

On a fresh new-format image, boot xv6 and run these separate shell commands:
  budget 2 100 0 fail
  group 2
  creatorprobe create
Stop QEMU, then run: python3 tests/check_creator_inode.py fs.img cg_old 2
Boot the same image again and run these separate shell commands:
  budget 3 100 0 fail
  group 3
  creatorprobe replace
Stop QEMU, then run:
  python3 tests/check_creator_inode.py fs.img cg_new 3 --absent cg_old
The creatorprobe output must show the same inode number in both boots.
"""

import argparse
import struct
from pathlib import Path

BSIZE = 1024
DINODE_SIZE = 68
IPB = BSIZE // DINODE_SIZE
FSMAGIC = 0x10203041


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("name")
    parser.add_argument("gid", type=int)
    parser.add_argument("--absent")
    args = parser.parse_args()

    data = Path(args.image).read_bytes()
    magic, size, _, _, _, _, inodestart, _ = struct.unpack_from("<8I", data, BSIZE)
    assert magic == FSMAGIC and len(data) == size * BSIZE, "wrong image format"

    def inode(inum):
        offset = (inodestart + inum // IPB) * BSIZE + inum % IPB * DINODE_SIZE
        kind, _, _, _, length, creator_gid, *addrs = struct.unpack_from(
            "<4H2I13I", data, offset
        )
        return kind, length, creator_gid, addrs

    root_kind, root_size, _, root_addrs = inode(1)
    assert root_kind == 1 and root_size <= 12 * BSIZE, "unexpected root directory"
    names = {}
    for offset in range(0, root_size, 16):
        block = root_addrs[offset // BSIZE]
        entry = block * BSIZE + offset % BSIZE
        inum = struct.unpack_from("<H", data, entry)[0]
        name = data[entry + 2 : entry + 16].split(b"\0", 1)[0].decode()
        if inum:
            names[name] = inum

    assert args.name in names, f"missing {args.name}"
    if args.absent:
        assert args.absent not in names, f"{args.absent} still exists"
    inum = names[args.name]
    kind, _, creator_gid, _ = inode(inum)
    assert kind == 2 and creator_gid == args.gid, (
        f"{args.name}: type={kind}, gid={creator_gid}, expected gid={args.gid}"
    )
    print(f"creator_image: PASS {args.name} inum={inum} gid={creator_gid}")


if __name__ == "__main__":
    main()
