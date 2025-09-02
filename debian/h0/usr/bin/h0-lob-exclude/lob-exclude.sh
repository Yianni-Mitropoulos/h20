#!/usr/bin/env bash
# h20-lob-exclude: remove /usr/local.orig/bin from /etc/profile.d/

set -euo pipefail
PROFILED_FILE="/etc/profile.d/local-orig.sh"

if [[ $EUID -ne 0 ]]; then
    exec sudo -n "$0" "$@"
fi

if [[ -e "$PROFILED_FILE" ]]; then
    rm -f -- "$PROFILED_FILE"
    echo "Disabled: /usr/local.orig/bin removed from PATH for future logins."
else
    echo "Not currently enabled."
fi
