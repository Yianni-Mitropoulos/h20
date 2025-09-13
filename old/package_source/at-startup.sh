#!/bin/bash
# Toggle a command to run at startup.
# Usage: at-startup <command ...>

set -euo pipefail

if ! command -v systemctl >/dev/null; then
  echo "systemd not found (need systemctl)"; exit 1
fi
if [ $# -lt 1 ]; then
  echo "Usage: at-startup <command>"; exit 1
fi

# First word is the program
PROG="$1"
shift

# Resolve absolute path if available
if CMD_PATH="$(command -v "$PROG" 2>/dev/null)"; then
  PROG="$CMD_PATH"
fi

CMD="$PROG $*"
HASH="$(printf '%s' "$CMD" | md5sum | cut -c1-8)"
UNIT="at-startup-${HASH}.service"
UNIT_PATH="/etc/systemd/system/${UNIT}"

# Escape single quotes for embedding
esc() {
  printf "%s" "$1" | sed "s/'/'\\\\''/g"
}
ESC_CMD="$(esc "$CMD")"

if [ -f "$UNIT_PATH" ]; then
  # Toggle OFF
  sudo systemctl disable --now "$UNIT" >/dev/null 2>&1 || true
  sudo rm -f "$UNIT_PATH"
  sudo systemctl daemon-reload
  echo "Startup command removed: $CMD"
  exit 0
fi

# Toggle ON
sudo tee "$UNIT_PATH" >/dev/null <<EOF
[Unit]
Description=Run at startup: $CMD
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/sh -lc '$ESC_CMD'
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$UNIT" >/dev/null
echo "Startup command registered: $CMD"
