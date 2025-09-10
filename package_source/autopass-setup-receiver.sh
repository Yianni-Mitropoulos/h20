#!/usr/bin/env bash
# Run this in sys-password so it knows how to handle data received via the
# local.SendDisposablePassword remote procedure call.

echo "Create autopass RPC handler."
sudo tee /etc/qubes-rpc/local.SendDisposablePassword >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail

LOG_FILE="$HOME/passwords.txt"

# Ensure the log file exists and is private
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"

vm="${QREXEC_REMOTE_DOMAIN:-unknown}"
ts="$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z')"

pw="$(cat)"

printf '%s %s %s\n' "$ts" "$vm" "$pw" >> "$LOG_FILE"
EOF

echo "Marking autopass RPC handler as executable."
sudo chmod 0755 /etc/qubes-rpc/local.SendDisposablePassword

echo "Success!"