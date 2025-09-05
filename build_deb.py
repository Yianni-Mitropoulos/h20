#!/usr/bin/env python3
"""
Builds <cwd>/h0.deb from shell scripts in <cwd>/scripts.

- Each scripts/*.sh becomes /usr/bin/h0-<basename> (executable) by default.
- Package name: hero-to-zero-utils
- Description: Hero to Zero Utilities Pack
- Architecture: all
- Output: h0.deb in current working directory
- Pure Python, no external tools required.

Usage:
  python make_h0_deb.py [--version 1.0.0] [--package hero-to-zero-utils] [--prefix /usr/bin]
"""
from __future__ import annotations
import argparse
import hashlib
import io
import os
from pathlib import Path
import tarfile
import time
from typing import List, Tuple

# ------------------------- helpers: ar (.deb) writer -------------------------

AR_MAGIC = b"!<arch>\n"
AR_FMAG  = b"`\n"

def _ar_pad_even(buf: io.BytesIO):
    if buf.tell() % 2 == 1:
        buf.write(b"\n")

def _ar_member_header(name: bytes, size: int, mtime: int = None, uid: int = 0, gid: int = 0, mode: int = 0o100644) -> bytes:
    if mtime is None:
        mtime = int(time.time())
    fields = [
        name.ljust(16, b' '),
        str(int(mtime)).encode().ljust(12, b' '),
        str(int(uid)).encode().ljust(6, b' '),
        str(int(gid)).encode().ljust(6, b' '),
        oct(mode)[2:].encode().ljust(8, b' '),
        str(int(size)).encode().ljust(10, b' '),
        AR_FMAG,
    ]
    header = b"".join(fields)
    if len(header) != 60:
        raise ValueError("Invalid ar header length")
    return header

def _ar_write_member(archive: io.BytesIO, name: str, data: bytes, *, mtime: int | None = None, uid: int = 0, gid: int = 0, mode: int = 0o100644):
    if not name.endswith('/'):
        name = name + '/'
    archive.write(_ar_member_header(name.encode(), len(data), mtime=mtime, uid=uid, gid=gid, mode=mode))
    archive.write(data)
    _ar_pad_even(archive)

# ------------------------- packager core -------------------------

def discover_scripts(scripts_dir: Path) -> List[Path]:
    if not scripts_dir.is_dir():
        raise SystemExit(f"Expected scripts directory at: {scripts_dir}")
    files = sorted(p for p in scripts_dir.glob("*.sh") if p.is_file())
    if not files:
        raise SystemExit(f"No .sh files found in {scripts_dir}")
    return files

def make_data_tar(scripts: List[Path], *, prefix: str) -> Tuple[bytes, List[Tuple[str, bytes]]]:
    """
    Build data.tar.gz with <prefix>/h0-<name> entries.
    Returns (gzip_bytes, [(path_inside_data_tar, file_bytes), ...]) for md5sums.
    """
    filelist: List[Tuple[str, bytes]] = []
    prefix = prefix.strip("/")

    raw = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=raw) as tf:
        for script in scripts:
            stem = script.stem  # foo for foo.sh
            out_name = f"h0-{stem}"
            tar_path = f"{prefix}/h0-{stem}"

            content = script.read_bytes()
            ti = tarfile.TarInfo(name=tar_path)
            ti.size = len(content)
            ti.mode = 0o100755
            ti.uid = 0
            ti.gid = 0
            ti.uname = "root"
            ti.gname = "root"
            ti.mtime = int(time.time())

            tf.addfile(ti, io.BytesIO(content))
            filelist.append((tar_path, content))
    return raw.getvalue(), filelist

def bytes_md5(data: bytes) -> str:
    h = hashlib.md5()
    h.update(data)
    return h.hexdigest()

def make_control_tar(package: str, version: str, description: str, filelist: List[Tuple[str, bytes]]) -> bytes:
    total_bytes = sum(len(b) for _, b in filelist)
    installed_size_kib = (total_bytes + 1023) // 1024 or 1

    control_fields = [
        f"Package: {package}",
        f"Version: {version}",
        "Section: utils",
        "Priority: optional",
        "Architecture: all",
        "Maintainer: Hero to Zero <devnull@example.com>",
        f"Installed-Size: {installed_size_kib}",
        f"Description: {description}",
    ]
    control_text = "\n".join(control_fields) + "\n"

    md5_text = "\n".join(f"{bytes_md5(data)}  {path}" for path, data in filelist)
    if md5_text:
        md5_text += "\n"

    raw = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=raw) as tf:
        # control
        cbytes = control_text.encode()
        cinfo = tarfile.TarInfo(name="control")
        cinfo.size = len(cbytes)
        cinfo.mode = 0o100644
        cinfo.uid = 0
        cinfo.gid = 0
        cinfo.uname = "root"
        cinfo.gname = "root"
        cinfo.mtime = int(time.time())
        tf.addfile(cinfo, io.BytesIO(cbytes))

        # md5sums
        mbytes = md5_text.encode()
        minfo = tarfile.TarInfo(name="md5sums")
        minfo.size = len(mbytes)
        minfo.mode = 0o100644
        minfo.uid = 0
        minfo.gid = 0
        minfo.uname = "root"
        minfo.gname = "root"
        minfo.mtime = int(time.time())
        tf.addfile(minfo, io.BytesIO(mbytes))

    return raw.getvalue()

def build_deb(package: str, version: str, description: str, scripts_dir: Path, out_path: Path, *, prefix: str):
    scripts = discover_scripts(scripts_dir)
    data_gz, filelist = make_data_tar(scripts, prefix=prefix)
    control_gz = make_control_tar(package, version, description, filelist)
    debian_binary = b"2.0\n"

    deb = io.BytesIO()
    deb.write(AR_MAGIC)
    _ar_write_member(deb, "debian-binary", debian_binary, mode=0o100644)
    _ar_write_member(deb, "control.tar.gz", control_gz, mode=0o100644)
    _ar_write_member(deb, "data.tar.gz", data_gz, mode=0o100644)
    out_path.write_bytes(deb.getvalue())

def main():
    parser = argparse.ArgumentParser(description="Package scripts/*.sh into h0.deb exposing h0-<name> commands.")
    parser.add_argument("--version", default="1.0.0", help="Package version (default: 1.0.0)")
    parser.add_argument("--package", default="h0", help="Debian package name (default: h0)")
    parser.add_argument("--scripts", default="package_source", help="Scripts directory (default: package_source)")
    parser.add_argument("--output", default="package_target/h0.deb", help="Output .deb path (default: package_target/h0.deb)")
    parser.add_argument("--prefix", default="/usr/bin", help="Install prefix inside package (default: /usr/bin)")
    args = parser.parse_args()

    cwd = Path.cwd()
    scripts_dir = (cwd / args.scripts).resolve()
    out_path = (cwd / args.output).resolve()
    description = "Hero to Zero Utilities Pack"

    # Warn about odd basenames
    bad = []
    for p in scripts_dir.glob("*.sh"):
        stem = p.stem
        import re
        if not re.fullmatch(r"[A-Za-z0-9._-]+", stem):
            bad.append(p.name)
    if bad:
        print("WARNING: These script basenames have characters that may not be ideal in command names:")
        for n in bad:
            print(f"  - {n}")
        print("They will still be packaged, but resulting commands may behave unexpectedly.")

    build_deb(args.package, args.version, description, scripts_dir, out_path, prefix=args.prefix)
    print(f"Built {out_path} with package '{args.package}' version {args.version}.")
    print(f"Each script *.sh is installed as {args.prefix.rstrip('/')}/h0-<basename>.")

if __name__ == "__main__":
    main()
