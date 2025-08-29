#!/usr/bin/env bash
# h0-cd-local-scripts: jump to the right /usr/local* dir and list scripts
# Works in TemplateVMs (/usr/local.orig) and AppVMs/Disposables (/usr/local).

set -euo pipefail

target=""
if [[ -d /usr/local.orig/bin ]]; then
    target="/usr/local.orig/bin"
elif [[ -d /usr/local/bin ]]; then
    target="/usr/local/bin"
else
    echo "Neither /usr/local.orig/bin nor /usr/local/bin found!" >&2
    exit 1
fi

cd "$target" || exit 1

# Show scripts in a readable way
echo "Now in: $PWD"
ls -lh --color=auto
