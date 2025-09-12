#!/usr/bin/env bash
set -euo pipefail

URL="https://github.com/GrapheneOS/hardened_malloc.git"
DIR="hardened_malloc_source"
BR="main"

# Remove any existing folder
rm -rf "$DIR"

# Shallow clone only the main branch
git clone --depth=1 --single-branch --branch "$BR" "$URL" "$DIR"

# Remove its .git and .github so it's just plain source files
rm -rf "$DIR/.git"
rm -rf "$DIR/.github"

echo "Refreshed $DIR from $URL ($BR), ready to commit"
