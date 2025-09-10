#!/usr/bin/env python3
from __future__ import annotations
import argparse, io, os, tarfile, time, hashlib, sys
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

def discover_scripts(sdir: Path) -> List[Path]:
    if not sdir.is_dir():
        raise SystemExit(f"scripts dir not found: {sdir}")
    files = sorted(p for p in sdir.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        raise SystemExit(f"no files in {sdir}")
    return files

def build_control(package: str, version: str, fields: Dict[str, str], filelist: List[Tuple[str, bytes]]) -> bytes:
    total_bytes = sum(len(b) for _, b in filelist)
    installed_size = max(1, (total_bytes + 1023) // 1024)
    ctrl = {
        "Package": package,
        "Version": version,
        "Installed-Size": str(installed_size),
        **fields,
    }
    ctrl.setdefault("Architecture", "all")
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

def make_data_tar(scripts: List[Path], prefix: str) -> Tuple[bytes, List[Tuple[str, bytes]]]:
    filelist: List[Tuple[str, bytes]] = []
    prefix = prefix.strip("/")
    # check stem collisions
    seen = {}
    for s in scripts:
        st = s.stem
        if st in seen:
            raise SystemExit(f"collision: {seen[st]} and {s}")
        seen[st] = s

    raw = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=raw) as tf:
        for s in scripts:
            target = f"{prefix}/h0-{s.stem}"
            content = s.read_bytes()
            ti = tarfile.TarInfo(name=target)
            ti.size = len(content)
            ti.mode = 0o100755
            ti.uid=ti.gid=0
            ti.uname=ti.gname="root"
            ti.mtime=int(time.time())
            tf.addfile(ti, io.BytesIO(content))
            filelist.append((target, content))
    return raw.getvalue(), filelist

def build_deb(package: str, version: str, scripts_dir: Path, out_path: Path, prefix: str, fields: Dict[str,str]):
    scripts = discover_scripts(scripts_dir)
    data_gz, filelist = make_data_tar(scripts, prefix)
    control_gz = build_control(package, version, fields, filelist)
    deb = io.BytesIO()
    deb.write(AR_MAGIC)
    _ar_write_member(deb, "debian-binary", b"2.0\n")
    _ar_write_member(deb, "control.tar.gz", control_gz)
    _ar_write_member(deb, "data.tar.gz", data_gz)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(deb.getvalue())

def main():
    ap = argparse.ArgumentParser(description="Package a directory of scripts as /usr/bin/h0-<name> commands.")
    ap.add_argument("scripts_dir")
    ap.add_argument("--package", default="h0")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--output", default="package_target/h0.deb")
    ap.add_argument("--prefix", default="/usr/bin")

    # Control fields (common)
    ap.add_argument("--section", dest="Section")
    ap.add_argument("--priority", dest="Priority")
    ap.add_argument("--architecture", dest="Architecture")
    ap.add_argument("--maintainer", dest="Maintainer")
    ap.add_argument("--depends", dest="Depends")
    ap.add_argument("--recommends", dest="Recommends")
    ap.add_argument("--suggests", dest="Suggests")
    ap.add_argument("--homepage", dest="Homepage")
    ap.add_argument("--description", dest="Description")

    # Extra free-form fields: --field Key=Value (repeatable)
    ap.add_argument("--field", action="append", default=[], help="Additional control field, e.g. --field Multi-Arch=same")

    args = ap.parse_args()

    fields = {k:v for k,v in vars(args).items() if k[0].isupper() and v}
    for eq in args.field:
        if "=" not in eq:
            raise SystemExit(f"--field expects Key=Value, got {eq!r}")
        k,v = eq.split("=",1)
        fields[k.strip()] = v.strip()

    build_deb(args.package, args.version, Path(args.scripts_dir).resolve(),
              Path(args.output).resolve(), args.prefix, fields)
    print(f"Built {Path(args.output).resolve()}")

if __name__ == "__main__":
    main()
