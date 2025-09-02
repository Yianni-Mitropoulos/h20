#!/usr/bin/env python3
"""
build_deb.py

Workflow:
1. Scan repo_source/ for *.sh
2. Ensure each script is mode 0755 (executable)
3. Generate debian/h0.install mapping each to /usr/bin/h0-<basename>
4. Run debuild -us -uc -b   (artifacts go into parent dir by default)
5. Move artifacts into repo_target/
6. Print resulting artifacts
"""

from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
from typing import List

def find_scripts(src: Path) -> List[Path]:
    scripts = sorted(src.rglob("*.sh"))
    if not scripts:
        sys.exit(f"ERROR: no .sh files under {src}")
    return scripts

def ensure_exec(scripts: List[Path]):
    changed = []
    for p in scripts:
        if (p.stat().st_mode & 0o111) == 0:
            os.chmod(p, 0o755)
            changed.append(p)
    if changed:
        print(f"Fixed permissions (+x): {len(changed)} file(s)")
        for p in changed:
            print(f"  - {p}")

def write_install_file(project_root: Path, scripts: List[Path], out_file: Path, prefix: str, rename_prefix: str):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    lines, bad = [], []
    for p in scripts:
        base = p.stem
        if not re.fullmatch(r"[A-Za-z0-9._+-]+", base):
            bad.append(p.name)
        rel = p.relative_to(project_root)   # <<< key fix: make path relative
        lines.append(f"{rel.as_posix()} {prefix.rstrip('/')}/{rename_prefix}{base}")
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_file} with {len(lines)} entries.")
    if bad:
        print("WARNING: Odd basenames (may be awkward as commands):")
        for n in bad:
            print(f"  - {n}")

def check_debian_dir(debian_dir: Path, package: str) -> Path:
    if not debian_dir.is_dir():
        sys.exit("ERROR: missing ./debian/ — create standard Debian packaging files.")
    required = [debian_dir/"control", debian_dir/"rules", debian_dir/"source"/"format"]
    missing = [p for p in required if not p.exists()]
    if missing:
        sys.exit("ERROR: missing files:\n  " + "\n  ".join(map(str, missing)))
    rules = debian_dir/"rules"
    if not (rules.stat().st_mode & 0o111):
        os.chmod(rules, rules.stat().st_mode | 0o755)
        print("Made debian/rules executable.")
    return debian_dir / "h0.install"

def run_debuild():
    print("\n=== Running: debuild -us -uc -b ===")
    try:
        subprocess.run(["debuild", "-us", "-uc", "-b"], check=True)
    except FileNotFoundError:
        sys.exit("ERROR: debuild not found. Install with: sudo apt install devscripts")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: debuild failed ({e.returncode})")

def move_artifacts(project_root: Path, build_dir: Path):
    parent = project_root.parent
    build_dir.mkdir(parents=True, exist_ok=True)
    patterns = ("*.deb", "*.dsc", "*.changes", "*.buildinfo",
                "*.orig.tar.*", "*.debian.tar.*", "*.tar.*")
    moved = 0
    for pat in patterns:
        for p in sorted(parent.glob(pat)):
            target = build_dir / p.name
            try:
                p.replace(target)
                moved += 1
            except Exception as ex:
                print(f"NOTE: could not move {p.name}: {ex}")
    print(f"\nMoved {moved} artifact(s) into {build_dir}")

def list_results(build_dir: Path):
    print("\nBuild artifacts in", build_dir)
    for a in sorted(build_dir.glob("*")):
        print("  -", a.name)

def main():
    project_root = Path.cwd()
    src_dir     = project_root / "package_source"
    debian_dir  = project_root / "debian"
    build_dir   = project_root / "package_target"

    scripts = find_scripts(src_dir)
    ensure_exec(scripts)

    install_path = check_debian_dir(debian_dir, "h0")
    write_install_file(project_root, scripts, install_path, "/usr/bin", "h0-")

    run_debuild()
    move_artifacts(project_root, build_dir)
    list_results(build_dir)

if __name__ == "__main__":
    main()
