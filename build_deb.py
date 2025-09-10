#!/usr/bin/env python3
"""
Builds <cwd>/h0.deb from files in <cwd>/package_source.

- Each file in package_source becomes /usr/bin/h0-<basename> (executable).
- Package name: configurable via --package (default: h0)
- Description and other control fields are loaded from <cwd>/deb_attributes.txt
- Architecture, Section, Priority, Maintainer, etc. should be provided in deb_attributes.txt
- Architecture defaults to "all" if not present in deb_attributes.txt
- Output: h0.deb at --output (default: package_target/h0.deb)
- Pure Python, no external tools required.

Usage:
  python make_h0_deb.py [--version 1.0.0] [--package hero-to-zero-utils] [--prefix /usr/bin] [--scripts package_source] [--output package_target/h0.deb] [--control-file deb_attributes.txt]
"""
from __future__ import annotations
import argparse
import hashlib
import io
import os
from pathlib import Path
import tarfile
import time
from typing import List, Tuple, Dict

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

# ------------------------- control file parsing -------------------------

def parse_control_file(path: Path) -> Dict[str, str]:
    """
    Parse a Debian control-style file (key: value with optional folded lines).
    - Ignores blank lines and comments beginning with '#'.
    - Supports multi-line values using continuation lines that start with a single space.
      Example:
        Description: Hero to Zero Utilities Pack
         This package provides ...
    Returns a dict mapping field names to their string values.
    """
    fields: Dict[str, str] = {}
    if not path.is_file():
        return fields

    current_key: str | None = None
    current_val_lines: List[str] = []

    def _commit():
        nonlocal current_key, current_val_lines
        if current_key is not None:
            fields[current_key] = "\n".join(current_val_lines).rstrip("\n")
        current_key = None
        current_val_lines = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            # blank or comment -> commit any pending field and continue
            if line.strip() == "":
                _commit()
            continue

        if line.startswith(" "):  # continuation
            if current_key is None:
                raise SystemExit(f"Continuation line encountered without a field in {path}: {line!r}")
            # Keep the leading space as per RFC822-style folding rules for Debian control files
            current_val_lines.append(line[1:])
            continue

        # New key: value line
        if ":" not in line:
            raise SystemExit(f"Invalid control field line in {path}: {line}")
        key, value = line.split(":", 1)
        _commit()
        current_key = key.strip()
        current_val_lines = [value.lstrip()]

    _commit()
    return fields

# ------------------------- packager core -------------------------

def discover_scripts(scripts_dir: Path) -> List[Path]:
    """
    Discover all non-hidden regular files in scripts_dir (non-recursive).
    """
    if not scripts_dir.is_dir():
        raise SystemExit(f"Expected scripts directory at: {scripts_dir}")
    files = sorted(
        p for p in scripts_dir.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )
    if not files:
        raise SystemExit(f"No non-hidden files found in {scripts_dir}")
    return files

def configure_permissions(scripts: List[Path]):
    """
    Ensure all provided files are set to 755 (rwxr-xr-x).
    """
    for script in scripts:
        try:
            script.chmod(0o755)
        except Exception as e:
            print(f"WARNING: Could not set permissions on {script}: {e}")

def make_data_tar(scripts: List[Path], *, prefix: str) -> Tuple[bytes, List[Tuple[str, bytes]]]:
    """
    Build data.tar.gz with <prefix>/h0-<stem> entries for every source file.
    Returns (gzip_bytes, [(path_inside_data_tar, file_bytes), ...]) for md5sums.
    """
    filelist: List[Tuple[str, bytes]] = []
    prefix = prefix.strip("/")

    # Detect collisions on output command names (same stem from different files)
    stems_seen = {}
    for s in scripts:
        stem = s.stem
        if stem in stems_seen:
            other = stems_seen[stem]
            raise SystemExit(
                "Name collision: multiple files map to the same command name:\n"
                f"  - {other}\n"
                f"  - {s}\n"
                "Consider renaming one of them."
            )
        stems_seen[stem] = s

    raw = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=raw) as tf:
        for script in scripts:
            stem = script.stem
            tar_path = f"{prefix}/h0-{stem}"

            content = script.read_bytes()
            ti = tarfile.TarInfo(name=tar_path)
            ti.size = len(content)
            # Executable bit for all included files
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

def make_control_tar(
    package: str,
    version: str,
    filelist: List[Tuple[str, bytes]],
    extra_fields: Dict[str, str],
) -> bytes:
    """
    Build control.tar.gz with:
      - control (merged fields)
      - md5sums (checksums of payload files)
    Field precedence:
      - Package and Version are taken from CLI arguments (this function's params).
      - Installed-Size is computed here and cannot be overridden.
      - All other fields come from extra_fields (deb_attributes.txt).
      - If Architecture is not present in extra_fields, default to "all".
    """
    total_bytes = sum(len(b) for _, b in filelist)
    installed_size_kib = (total_bytes + 1023) // 1024 or 1

    # Start with required/derived fields
    control_fields: Dict[str, str] = {
        "Package": package,
        "Version": version,
        "Installed-Size": str(installed_size_kib),
    }

    # Merge external fields
    for k, v in extra_fields.items():
        # Do not allow overriding Installed-Size; keep CLI for Package/Version
        if k in ("Installed-Size", "Package", "Version"):
            continue
        control_fields[k] = v

    # Ensure Architecture has a sensible default if not given
    control_fields.setdefault("Architecture", "all")

    # Produce Debian control text (order is not strictly required, but we try a common order)
    preferred_order = [
        "Package",
        "Version",
        "Section",
        "Priority",
        "Architecture",
        "Maintainer",
        "Installed-Size",
        "Depends",
        "Recommends",
        "Suggests",
        "Homepage",
        "Description",
    ]
    # Keep preferred order first, then append any remaining keys
    ordered_keys = [k for k in preferred_order if k in control_fields]
    ordered_keys += [k for k in control_fields.keys() if k not in ordered_keys]

    def _format_field(k: str, v: str) -> str:
        if "\n" not in v:
            return f"{k}: {v}"
        # For multi-line, Debian control files use continuation lines starting with a space.
        first, *rest = v.splitlines()
        return "\n".join(
            [f"{k}: {first}"] + [f" {line}" for line in rest]
        )

    control_text = "\n".join(_format_field(k, control_fields[k]) for k in ordered_keys) + "\n"

    # md5sums content
    md5_text = "\n".join(f"{bytes_md5(data)}  {path}" for path, data in filelist)
    if md5_text:
        md5_text += "\n"

    raw = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=raw) as tf:
        # control
        cbytes = control_text.encode("utf-8")
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
        mbytes = md5_text.encode("utf-8")
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

def build_deb(
    package: str,
    version: str,
    scripts_dir: Path,
    out_path: Path,
    *,
    prefix: str,
    extra_fields: Dict[str, str],
):
    scripts = discover_scripts(scripts_dir)
    configure_permissions(scripts)
    data_gz, filelist = make_data_tar(scripts, prefix=prefix)
    control_gz = make_control_tar(package, version, filelist, extra_fields)
    debian_binary = b"2.0\n"

    # Ensure output directory exists
    out_path.parent.mkdir(parents=True, exist_ok=True)

    deb = io.BytesIO()
    deb.write(AR_MAGIC)
    _ar_write_member(deb, "debian-binary", debian_binary, mode=0o100644)
    _ar_write_member(deb, "control.tar.gz", control_gz, mode=0o100644)
    _ar_write_member(deb, "data.tar.gz", data_gz, mode=0o100644)
    out_path.write_bytes(deb.getvalue())

def main():
    parser = argparse.ArgumentParser(description="Build h0.deb from package_source exposing h0-<basename> commands.")
    parser.add_argument("--version", default="1.0.0", help="Package version (default: 1.0.0)")
    parser.add_argument("--package", default="h0", help="Debian package name (default: h0)")
    parser.add_argument("--scripts", default="package_source", help="Source directory (default: package_source)")
    parser.add_argument("--output", default="package_target/h0.deb", help="Output .deb path (default: package_target/h0.deb)")
    parser.add_argument("--prefix", default="/usr/bin", help="Install prefix inside package (default: /usr/bin)")
    parser.add_argument("--control-file", default="deb_attributes.txt", help="Path to external control fields (default: deb_attributes.txt)")
    args = parser.parse_args()

    cwd = Path.cwd()
    scripts_dir = (cwd / args.scripts).resolve()
    out_path = (cwd / args.output).resolve()
    control_path = (cwd / args.control_file).resolve()

    # Warn about odd basenames
    bad = []
    if scripts_dir.is_dir():
        for p in scripts_dir.iterdir():
            if not p.is_file() or p.name.startswith("."):
                continue
            stem = p.stem
            import re
            if not re.fullmatch(r"[A-Za-z0-9._-]+", stem):
                bad.append(p.name)
    if bad:
        print("WARNING: These basenames have characters that may not be ideal in command names:")
        for n in bad:
            print(f"  - {n}")
        print("They will still be packaged as h0-<basename>, but resulting commands may behave unexpectedly.")

    # Load external control fields
    extra_fields = parse_control_file(control_path)
    if not extra_fields:
        print(f"NOTE: No external control fields loaded from {control_path}. Using defaults where applicable.")
        # Provide a minimal sensible default if file is missing/empty.
        # (Architecture defaults to 'all' in make_control_tar)
        extra_fields = {
            # Example defaults you might want if the file is missing:
            # "Section": "utils",
            # "Priority": "optional",
            # "Maintainer": "Hero to Zero <devnull@example.com>",
            # "Description": "Hero to Zero Utilities Pack",
        }

    build_deb(
        args.package,
        args.version,
        scripts_dir,
        out_path,
        prefix=args.prefix,
        extra_fields=extra_fields,
    )
    print(f"Built {out_path} with package '{args.package}' version {args.version}.")
    print(f"Each file is installed as {args.prefix.rstrip('/')}/h0-<basename>.")
    print(f"Control fields loaded from: {control_path}")

if __name__ == "__main__":
    main()
