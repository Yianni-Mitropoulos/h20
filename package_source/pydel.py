#!/usr/bin/env python3
import sys
import os
from collections import defaultdict, Counter
from pathlib import Path

def read_spec_from_stdin() -> dict:
    """
    Read a spec from stdin in the form:
        file1.py
          def foo
          class Bar
        subdir/file2.py
          def baz

    Returns: dict[str, list[str]] mapping filename -> list of prefixes (deduped, order-preserving).
    Empty lines are ignored. A line starting with non-space/tab begins a new filename section.
    Lines indented by at least one space or tab are prefixes for the most recent filename.
    """
    if len(sys.argv) != 1:
        print(f"Usage: {Path(sys.argv[0]).name}  (no arguments accepted)")
        sys.exit(1)

    data = sys.stdin.read()
    if not data.strip():
        print("No spec provided on stdin. Exiting.")
        sys.exit(0)

    file_to_prefixes = defaultdict(list)
    current_file = None
    seen_per_file = defaultdict(set)

    for raw in data.splitlines():
        if not raw.strip():
            continue  # ignore empty lines in the spec

        if raw[0].isspace():
            # indented -> prefix for current file
            if current_file is None:
                print("Error: Found an indented prefix line before any filename. Aborting.")
                sys.exit(1)
            prefix = raw.strip()
            if not prefix:
                continue
            if prefix not in seen_per_file[current_file]:
                file_to_prefixes[current_file].append(prefix)
                seen_per_file[current_file].add(prefix)
        else:
            # new filename
            current_file = raw.strip()
            if current_file not in file_to_prefixes:
                file_to_prefixes[current_file] = []

    # drop files with no prefixes
    for f in [f for f, ps in file_to_prefixes.items() if not ps]:
        del file_to_prefixes[f]

    if not file_to_prefixes:
        print("No valid filename + prefix pairs found in the spec. Exiting.")
        sys.exit(0)

    return file_to_prefixes

def is_block_header(line_lstripped: str, prefixes) -> str | None:
    """
    If the left-stripped line ends with ':' AND starts with one of the prefixes,
    return that matching prefix; else return None.
    """
    if not line_lstripped.endswith(":"):
        return None
    for p in prefixes:
        if line_lstripped.startswith(p):
            return p
    return None

def find_comment_block_start(lines, header_index: int) -> int:
    """
    Given the index of a block header, walk upward and include any *contiguous* comment
    lines (after left-strip, starting with '#'). Stop when hitting a non-comment or the file start.
    A blank line breaks adjacency and is NOT included.
    Returns the index (inclusive) where deletion should start.
    """
    i = header_index - 1
    start = header_index
    while i >= 0:
        s = lines[i]
        if s.strip() == "":
            break  # blank line breaks adjacency
        if s.lstrip().startswith("#"):
            start = i
            i -= 1
            continue
        break
    return start

def delete_blocks_in_file(filename: str, prefixes: list[str]) -> tuple[list[str], Counter]:
    """
    Load file, delete matching blocks (and contiguous # comments above), and
    return (new_lines, matches_counter) where matches_counter counts matches per *prefix*.
    """
    with open(filename, "r", encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    i = 0
    n = len(lines)
    matches = Counter()

    while i < n:
        raw = lines[i].rstrip("\n")
        lstripped = raw.lstrip()

        matched_prefix = is_block_header(lstripped, prefixes)
        if matched_prefix is not None:
            # Determine deletion start (include contiguous # comments directly above)
            delete_start = find_comment_block_start(lines, i)

            # Retract already-emitted comment lines from out, if any.
            to_retract = i - delete_start
            if to_retract > 0 and len(out) > 0:
                retract = min(to_retract, len(out))
                if retract > 0:
                    del out[-retract:]

            base_indent = len(raw) - len(raw.lstrip())
            j = i + 1
            # Consume the block by indentation
            while j < n:
                nxt_raw = lines[j].rstrip("\n")
                if nxt_raw.strip() == "":
                    j += 1
                    continue
                nxt_indent = len(nxt_raw) - len(nxt_raw.lstrip())
                if nxt_indent <= base_indent:
                    break
                j += 1

            # Drop lines [delete_start, j)
            matches[matched_prefix] += 1
            i = j
            continue

        # Not a targeted header; keep the line
        out.append(lines[i])
        i += 1

    return out, matches

def main():
    # Read and resolve spec relative to CWD; expand ~ for convenience
    spec = read_spec_from_stdin()

    # Resolve to absolute paths (messages are clearer), but behavior is relative to CWD by default
    resolved_spec = {}
    for fname, prefixes in spec.items():
        resolved = str(Path(fname).expanduser().resolve())
        resolved_spec[resolved] = prefixes

    any_changes = False
    warnings = []

    for filename, prefixes in resolved_spec.items():
        if not os.path.isfile(filename):
            print(f"[SKIP] {filename}: file not found.")
            continue

        new_lines, matches = delete_blocks_in_file(filename, prefixes)

        # Collect warnings: any prefix that matched more than once in this file
        dups = {p: c for p, c in matches.items() if c > 1}
        if dups:
            warnings.append((filename, dups))

        # If there were any matches, write back
        total = sum(matches.values())
        if total > 0:
            with open(filename, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            any_changes = True
            matched_list = ", ".join(f"'{p}': {matches[p]}" for p in sorted(matches))
            print(f"[OK]   {filename}: removed {total} block(s) [{matched_list}]")
        else:
            print(f"[NOOP] {filename}: no matching blocks found.")

    # Print warnings for duplicates after all files processed
    if warnings:
        print("\nWarnings:")
        for fname, dupmap in warnings:
            items = ", ".join(f"'{p}' matched {dupmap[p]} times" for p in sorted(dupmap))
            print(f"  {fname}: {items}")

    if not any_changes and not warnings:
        print("No changes made.")

if __name__ == "__main__":
    main()
