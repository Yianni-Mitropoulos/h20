#!/usr/bin/env python3
from __future__ import annotations
import argparse, io, os, tarfile, time, hashlib, sys, subprocess
from pathlib import Path
from typing import Dict, List, Tuple

AR_MAGIC = b"!<arch>\n"
AR_FMAG  = b"`\n"

def _ar_pad_even(buf: io.BytesIO):
    if buf.tell() % 2 == 1:
        buf.write(b"\n")

def _ar_member_header(name: bytes, size: int, mtime: int | None = None, uid: int = 0, gid: int = 0, mode: int = 0o100644) -> bytes:
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
    hdr = b"".join(fields)
    if len(hdr) != 60:
        raise ValueError("invalid ar header")
    return hdr

def _ar_write_member(archive: io.BytesIO, name: str, data: bytes, *, mtime: int | None = None, uid: int = 0, gid: int = 0, mode: int = 0o100644):
    if not name.endswith('/'):
        name = name + '/'
    archive.write(_ar_member_header(name.encode(), len(data), mtime=mtime, uid=uid, gid=gid, mode=mode))
    archive.write(data)
    _ar_pad_even(archive)

def md5(data: bytes) -> str:
    h = hashlib.md5(); h.update(data); return h.hexdigest()

def build_control(package: str, version: str, fields: Dict[str, str], filelist: List[Tuple[str, bytes]]) -> bytes:
    total_bytes = sum(len(b) for _, b in filelist)
    installed_size = max(1, (total_bytes + 1023) // 1024)
    ctrl = {
        "Package": package,
        "Version": version,
        "Installed-Size": str(installed_size),
        **fields,
    }
    order = ["Package","Version","Section","Priority","Architecture","Maintainer","Installed-Size","Depends","Recommends","Suggests","Homepage","Description"]
    keys = [k for k in order if k in ctrl] + [k for k in ctrl.keys() if k not in order]

    def fmt(k,v):
        if "\n" not in v: return f"{k}: {v}"
        first,*rest = v.splitlines()
        return "\n".join([f"{k}: {first}"] + [f" {line}" for line in rest])

    control_txt = "\n".join(fmt(k, ctrl[k]) for k in keys) + "\n"
    md5s = "\n".join(f"{md5(b)}  {p}" for p,b in filelist)
    if md5s: md5s += "\n"

    raw = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=raw) as tf:
        for name, data in (("control", control_txt.encode()), ("md5sums", md5s.encode())):
            ti = tarfile.TarInfo(name=name)
            ti.size = len(data); ti.mode = 0o100644; ti.uid=ti.gid=0
            ti.uname=ti.gname="root"; ti.mtime=int(time.time())
            tf.addfile(ti, io.BytesIO(data))
    return raw.getvalue()

def _tar_add(tf: tarfile.TarFile, path_in_tar: str, content: bytes, mode: int):
    ti = tarfile.TarInfo(name=path_in_tar)
    ti.size = len(content)
    ti.mode = mode
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = "root"
    ti.mtime = int(time.time())
    tf.addfile(ti, io.BytesIO(content))

def main():
    ap = argparse.ArgumentParser(description="Build & package a Makefile project producing a shared library.")
    ap.add_argument("source_dir")
    ap.add_argument("--package", default="hardened-malloc")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--output", default="package_target/hardened-malloc.deb")

    # Multiarch placement
    ap.add_argument("--architecture", dest="Architecture", default="amd64", choices=["amd64","arm64"])
    ap.add_argument("--lib-name", default="libhardened_malloc.so", help="Shared object filename produced by make")
    ap.add_argument("--lib-subdir", default=None, help="Override multiarch subdir (x86_64-linux-gnu / aarch64-linux-gnu)")
    ap.add_argument("--lib-mode", default="0644", help="Octal mode for the .so (default 0644)")

    # Extra tools
    ap.add_argument("--wrap", action="store_true", help="Install /usr/bin/<package>-wrap (LD_PRELOAD wrapper)")
    ap.add_argument("--preload-tool", action="store_true", help="Install /usr/sbin/<package>-preload-everywhere toggler")
    ap.add_argument("--preload-config", default="/etc/ld.so.preload", help="Config path edited by the toggler (default /etc/ld.so.preload)")

    # Control fields
    ap.add_argument("--maintainer", dest="Maintainer")
    ap.add_argument("--section", dest="Section")
    ap.add_argument("--priority", dest="Priority")
    ap.add_argument("--depends", dest="Depends")
    ap.add_argument("--recommends", dest="Recommends")
    ap.add_argument("--suggests", dest="Suggests")
    ap.add_argument("--homepage", dest="Homepage")
    ap.add_argument("--description", dest="Description")
    ap.add_argument("--field", action="append", default=[], help="Extra control field Key=Value")

    args = ap.parse_args()

    src = Path(args.source_dir).resolve()
    if not src.is_dir():
        raise SystemExit(f"source dir not found: {src}")

    # Build with make
    subprocess.check_call(["make", "-C", str(src)])

    # Locate artifact
    artifact = None
    for candidate in (src/args.lib_name, src/"build"/args.lib_name, src/"out"/args.lib_name):
        if candidate.exists():
            artifact = candidate; break
    if artifact is None:
        raise SystemExit(f"{args.lib_name} not found in {src}/ (or build/, out/)")

    triplet = args.lib_subdir or {"amd64":"x86_64-linux-gnu","arm64":"aarch64-linux-gnu"}[args.Architecture]
    lib_target_rel = f"usr/lib/{triplet}/{args.lib_name}"
    lib_target_abs = f"/{lib_target_rel}"

    # Build data.tar.gz
    filelist: List[Tuple[str, bytes]] = []
    data_raw = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=data_raw) as tf:
        # Library
        lib_bytes = artifact.read_bytes()
        _tar_add(tf, lib_target_rel, lib_bytes, int(args.lib_mode, 8))
        filelist.append((lib_target_rel, lib_bytes))

        # Optional wrapper: /usr/bin/<package>-wrap
        if args.wrap:
            wrap_name = f"usr/bin/{args.package}-wrap"
            wrap_sh = f"""#!/bin/sh
# Wrapper to run a command with {args.package} via LD_PRELOAD
export LD_PRELOAD="{lib_target_abs}"
exec "$@"
"""
            _tar_add(tf, wrap_name, wrap_sh.encode(), 0o100755)
            filelist.append((wrap_name, wrap_sh.encode()))

        # Optional preload-everywhere toggler: /usr/sbin/<package>-preload-everywhere
        if args.preload_tool:
            tool_name = f"usr/sbin/{args.package}-preload-everywhere"
            tool_sh = f"""#!/bin/sh
# Enable/disable global preloading of {args.package}
set -eu
CONF="{args.preload_config}"
LIB="{lib_target_abs}"

need_root() {{
  if [ "$(id -u)" -ne 0 ]; then
    echo "This action requires root. Try: sudo $0 $@" >&2
    exit 1
  fi
}}

backup() {{
  if [ -f "$CONF" ]; then
    cp -a "$CONF" "$CONF.$(date +%Y%m%d-%H%M%S).bak"
  fi
}}

contains_line() {{
  [ -f "$CONF" ] && grep -Fx -- "$LIB" "$CONF" >/dev/null 2>&1
}}

enable() {{
  need_root
  backup
  mkdir -p "$(dirname "$CONF")"
  touch "$CONF"
  if ! contains_line; then
    # Remove any existing partial/duplicate entries first
    tmp="$(mktemp)"
    if [ -s "$CONF" ]; then
      grep -Fxv -- "$LIB" "$CONF" >"$tmp" || true
    fi
    echo "$LIB" >>"$tmp"
    mv "$tmp" "$CONF"
  fi
  echo "Enabled global preload of: $LIB (in $CONF)"
}}

disable() {{
  need_root
  [ -f "$CONF" ] || {{ echo "Nothing to disable (no $CONF)"; exit 0; }}
  backup
  tmp="$(mktemp)"
  grep -Fxv -- "$LIB" "$CONF" >"$tmp" || true
  if [ ! -s "$tmp" ]; then
    rm -f "$CONF" "$tmp"
    echo "Disabled (removed empty $CONF)"
  else
    mv "$tmp" "$CONF"
    echo "Disabled (removed entry; kept $CONF)"
  fi
}}

status() {{
  if contains_line; then
    echo "ENABLED: $LIB present in $CONF"
    exit 0
  else
    echo "DISABLED: $LIB not present in $CONF"
    exit 1
  fi
}}

case "${{1:-}}" in
  enable) shift; enable "$@";;
  disable) shift; disable "$@";;
  status) shift; status "$@";;
  print-path) echo "$LIB";;
  *) echo "Usage: $0 {{enable|disable|status|print-path}}" >&2; exit 2;;
esac
"""
            _tar_add(tf, tool_name, tool_sh.encode(), 0o100755)
            filelist.append((tool_name, tool_sh.encode()))

    data_gz = data_raw.getvalue()

    # control.tar.gz
    fields = {k:v for k,v in vars(args).items() if k[0].isupper() and v}
    for eq in args.field:
        if "=" not in eq:
            raise SystemExit(f"--field expects Key=Value, got {eq!r}")
        k,v = eq.split("=",1)
        fields[k.strip()] = v.strip()
    control_gz = build_control(args.package, args.version, fields, filelist)

    # Build .deb
    deb = io.BytesIO()
    deb.write(AR_MAGIC)
    _ar_write_member(deb, "debian-binary", b"2.0\n")
    _ar_write_member(deb, "control.tar.gz", control_gz)
    _ar_write_member(deb, "data.tar.gz", data_gz)
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(deb.getvalue())
    print(f"Built {out}")

if __name__ == "__main__":
    main()
