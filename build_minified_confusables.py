#!/usr/bin/env python3
import os

def minify_confusables(infile: str, outfile: str):
    """
    Strip comments and whitespace from confusables.txt, leaving just:
    <src> ; <dst> ; <status>
    """
    with open(infile, encoding="utf-8") as f, open(outfile, "w", encoding="utf-8") as out:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Drop everything after the first '#'
            core = line.split("#", 1)[0].strip()
            if core:
                out.write(core + "\n")

if __name__ == "__main__":
    infile = "confusables.txt"
    outfile = os.path.join("zeropad", "confusables-minified.txt")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(outfile), exist_ok=True)

    minify_confusables(infile, outfile)
    print(f"Minified confusables written to {outfile}")
