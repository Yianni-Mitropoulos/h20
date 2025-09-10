#!/usr/bin/env bash

# Default number of lines
LINES=200

# If an argument is provided, use it instead
if [ -n "$1" ]; then
  LINES="$1"
fi

# Run journalctl with the given (or default) number of lines
journalctl -n "$LINES" -f --no-hostname --output=short-iso
