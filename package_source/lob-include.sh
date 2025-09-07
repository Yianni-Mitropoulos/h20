#!/usr/bin/env bash
# h0-lob-include: add /usr/local.orig/bin to /etc/profile.d/ and thus to PATH system-wide

set -euo pipefail
TARGET="/usr/local.orig/bin"
PROFILED_FILE="/etc/profile.d/local-orig.sh"

if [[ $EUID -ne 0 ]]; then
    exec sudo -n "$0" "$@"
fi

if [[ ! -d "$TARGET" ]]; then
    echo "Error: $TARGET does not exist (normal outside TemplateVMs)." >&2
    exit 1
fi

if [[ -e "$PROFILED_FILE" ]]; then
    echo "Already enabled via $PROFILED_FILE"
else
    printf 'export PATH="%s:$PATH"\n' "$TARGET" > "$PROFILED_FILE"
    chmod 0644 "$PROFILED_FILE"
    echo "Enabled: $TARGET will be in PATH for all users on next login."
fi
