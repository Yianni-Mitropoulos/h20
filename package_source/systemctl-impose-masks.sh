#!/usr/bin/env bash
# Re-mask units listed in /etc/h0-systemctl-list (one .service/.socket per line).
# No expansion logic lives here; file must contain explicit unit names.
set -euo pipefail

LIST_FILE=${LIST_FILE:-/etc/h0-systemctl-list}

read_units() {
  [[ -r "$LIST_FILE" ]] || return 0
  # strip trailing comments; trim; drop blanks
  sed -E 's/[[:space:]]+#.*$//' "$LIST_FILE" \
  | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' \
  | awk 'NF'
}

apply() {
  mapfile -t units < <(read_units || true)
  ((${#units[@]})) || exit 0

  # de-duplicate and only keep valid explicit units
  mapfile -t units < <(printf '%s\n' "${units[@]}" \
    | grep -E '^[A-Za-z0-9@:._-]+\.(service|socket)$' \
    | sort -u)

  for u in "${units[@]}"; do
    systemctl mask "$u" >/dev/null 2>&1 || true
  done
}

case "${1:-apply}" in
  apply) apply ;;
  *) echo "Usage: $0 [apply]" >&2; exit 1 ;;
esac
