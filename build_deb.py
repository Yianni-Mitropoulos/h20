#!/usr/bin/env python3
import argparse, os, pathlib, shlex, subprocess, sys, textwrap

# Map control keys to flag names for each script (common single-dash form)
KEY_TO_FLAG = {
    "Package": "--package",
    "Version": "--version",
    "Section": "--section",
    "Priority": "--priority",
    "Architecture": "--architecture",
    "Maintainer": "--maintainer",
    "Depends": "--depends",
    "Recommends": "--recommends",
    "Suggests": "--suggests",
    "Homepage": "--homepage",
    "Description": "--description",
}

def parse_blocks(text: str):
    blocks = []
    cur = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("./"):
            if cur: blocks.append(cur)
            cur = {"cmdline": line, "fields": []}
        else:
            if cur is None:
                raise SystemExit("First non-empty line must start with ./")
            cur["fields"].append(line)
    if cur: blocks.append(cur)
    return blocks

def parse_fields(lines):
    fields = {}
    extras = []
    curk = None
    curv = []
    def commit():
        nonlocal curk, curv
        if curk is not None:
            fields[curk] = "\n".join(curv).rstrip("\n")
        curk, curv = None, []
    for ln in lines:
        if ln.startswith(" "):  # continuation
            if curk is None: raise SystemExit(f"Continuation without key: {ln!r}")
            curv.append(ln[1:])
            continue
        if ":" not in ln:
            # ignore comments
            if ln.lstrip().startswith("#"): continue
            extras.append(ln)
            continue
        commit()
        k,v = ln.split(":",1)
        curk = k.strip()
        curv = [v.lstrip()]
    commit()
    return fields, extras

def build_argv(cmdline: str, fields: dict):
    base = shlex.split(cmdline)
    argv = [*base]
    extra_fields = []
    for k, v in fields.items():
        flag = KEY_TO_FLAG.get(k)
        if flag:
            argv += [flag, v]
        else:
            extra_fields.append((k, v))
    for k,v in extra_fields:
        argv += ["--field", f"{k}={v}"]
    return argv

def main():
    ap = argparse.ArgumentParser(description="Drive multiple deb builds from deb_attributes.txt headings.")
    ap.add_argument("attributes_file", nargs="?", default="deb_attributes.txt")
    args = ap.parse_args()

    path = pathlib.Path(args.attributes_file)
    if not path.exists():
        sys.exit(f"missing {path}")

    blocks = parse_blocks(path.read_text(encoding="utf-8"))
    if not blocks:
        sys.exit("no build blocks found")

    for i, blk in enumerate(blocks, 1):
        fields, _ = parse_fields(blk["fields"])
        argv = build_argv(blk["cmdline"], fields)
        print(f"\n==> [{i}/{len(blocks)}] {' '.join(map(shlex.quote, argv))}")
        subprocess.check_call(argv)

    print("\nAll builds completed.")

if __name__ == "__main__":
    main()
