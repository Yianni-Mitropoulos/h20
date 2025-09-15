#!/usr/bin/env python3
"""
make_prompt_txt.py

Recursively scan the current working directory for .py files and write a single
'prompt.txt' file with this structure:

relative/path/to/file1.py
    <file1 contents, each line indented by 4 spaces>
relative/path/to/subdir/file2.py
    <file2 contents, each line indented by 4 spaces>
...

Notes:
- Paths are shown relative to the cwd when you run this script.
- Common junk directories are skipped (e.g., .git, __pycache__, venvs, node_modules).
- Encoding is utf-8; undecodable bytes are safely replaced.
"""

from __future__ import annotations
import os
from pathlib import Path

# You can tweak this set if needed
IGNORE_DIRS = {
    ".git", "__pycache__", ".mypy_cache", ".pytest_cache",
    "node_modules", "site-packages", "dist", "build",
    ".venv", "venv", "env",
}

INDENT = "    "

def iter_python_files(base: Path):
    """Yield Path objects for all .py files under base, pruning IGNORE_DIRS."""
    # Ensure deterministic ordering
    for root, dirs, files in os.walk(base, topdown=True, followlinks=False):
        # Prune ignored dirs in-place
        dirs[:] = sorted([d for d in dirs if d not in IGNORE_DIRS])
        # Sort files for stable output
        for fname in sorted(files):
            if fname.endswith(".py"):
                yield Path(root) / fname

def main():
    base = Path.cwd()
    out_path = base / "prompt.txt"

    python_files = sorted(
        (p for p in iter_python_files(base)),
        key=lambda p: p.relative_to(base).as_posix()
    )

    with out_path.open("w", encoding="utf-8", newline="\n") as out:
        first = True
        for p in python_files:
            rel = p.relative_to(base).as_posix()
            # Write header (no extra blank lines between files, matching your example)
            out.write(f"{rel}\n")
            # Write file contents, each line indented by 4 spaces. Preserve empty lines (indented).
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for line in f.read().splitlines():
                    out.write(INDENT + line + "\n")

    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
