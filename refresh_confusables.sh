#!/bin/sh
# Refresh Unicode confusables.txt into the current working directory

URL="https://www.unicode.org/Public/security/latest/confusables.txt"
OUTFILE="confusables.txt"

echo "Downloading $URL ..."

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$URL" -o "$OUTFILE"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$OUTFILE" "$URL"
else
  echo "Error: neither curl nor wget is installed." >&2
  exit 1
fi

if [ -f "$OUTFILE" ]; then
  echo "Saved to $OUTFILE"
else
  echo "Download failed" >&2
  exit 1
fi
