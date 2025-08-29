#!/usr/bin/env bash
# h20-lob-status: check whether /usr/local.orig/bin is in /etc/profile.d/ and thus in PATH system-wide

set -euo pipefail
TARGET="/usr/local.orig/bin"
PROFILED_FILE="/etc/profile.d/local-orig.sh"

if echo "$PATH" | tr ':' '\n' | grep -qx "$TARGET"; then
    echo "CURRENT SESSION: $TARGET is in PATH"
else
    echo "CURRENT SESSION: $TARGET is NOT in PATH"
fi

if [[ -e "$PROFILED_FILE" ]]; then
    echo "PERSISTENCE: enabled via $PROFILED_FILE"
else
    echo "PERSISTENCE: not enabled"
fi

if [[ ! -d "$TARGET" ]]; then
    echo "Note: $TARGET does not exist on this VM (normal outside TemplateVMs)."
fi
