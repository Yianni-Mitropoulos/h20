#!/usr/bin/env python3
import sys
import os

def read_prefixes():
    print("Paste the prefixes that should match block headers (lines ending with ':').")
    print("Each non-empty line here is a prefix. Press CTRL+D (CTRL+Z then Enter on Windows) when done.\n")
    data = sys.stdin.read()
    # Keep only non-empty, stripped lines as prefixes
    prefixes = [line.strip() for line in data.splitlines() if line.strip() != ""]
    # De-duplicate but preserve order
    seen = set()
    uniq = []
    for p in prefixes:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    if not uniq:
        print("No prefixes provided. Exiting.")
        sys.exit(0)
    return uniq

def is_block_header(line_lstripped: str, prefixes) -> bool:
    # Must end with ':' to be a Python block header and start with any provided prefix
    if not line_lstripped.endswith(":"):
        return False
    for p in prefixes:
        if line_lstripped.startswith(p):
            return True
    return False

def delete_blocks(lines, prefixes):
    out = []
    i = 0
    n = len(lines)

    while i < n:
        raw = lines[i].rstrip("\n")
        lstripped = raw.lstrip()

        # Match: leading whitespace allowed before the prefix; header must end with ':'
        if is_block_header(lstripped, prefixes):
            base_indent = len(raw) - len(raw.lstrip())
            i += 1
            # Skip the whole indented block
            while i < n:
                nxt_raw = lines[i].rstrip("\n")
                if nxt_raw.strip() == "":
                    i += 1
                    continue
                nxt_indent = len(nxt_raw) - len(nxt_raw.lstrip())
                if nxt_indent <= base_indent:
                    break
                i += 1
            # Do not append the header or its block
            continue

        # Not a targeted header; keep the line
        out.append(lines[i])
        i += 1

    return out

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <filename>")
        sys.exit(1)

    filename = sys.argv[1]
    if not os.path.isfile(filename):
        print(f"Error: file '{filename}' not found.")
        sys.exit(1)

    with open(filename, "r", encoding="utf-8") as f:
        lines = f.readlines()

    prefixes = read_prefixes()

    new_lines = delete_blocks(lines, prefixes)

    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"Updated file written to {filename}")

if __name__ == "__main__":
    main()
