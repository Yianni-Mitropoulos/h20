#!/usr/bin/env bash
# h0-root-confer: grant passwordless sudo for ONE command to a user
# Usage:
#   h0-root-confer <command> [--user USER]
# Notes:
#   - Accepts an absolute path or a bare name (resolved via `command -v`).
#   - If resolved path is under /usr/local.orig/, we map it to the equivalent
#     /usr/local/ path for sudoers (Qubes-friendly).
#   - Idempotent: avoids duplicate sudoers lines. Validates with visudo.

set -euo pipefail

die() { echo "Error: $*" >&2; exit 1; }

# Re-exec as root (requires bootstrap sudoers allowing this helper)
if [[ $EUID -ne 0 ]]; then
  exec sudo -n -- "$0" "$@"
fi

user="${SUDO_USER:-${USER:-}}"
cmd=""

# --- args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) shift; [[ $# -gt 0 ]] || die "--user requires a value"; user="$1"; shift ;;
    -*)     die "Unknown option: $1" ;;
    *)      [[ -z "$cmd" ]] || die "Only one command may be granted at a time"; cmd="$1"; shift ;;
  esac
done

[[ -n "$user" ]] || die "Could not determine target user"
[[ -n "$cmd"  ]] || die "Usage: h0-root-confer <command> [--user USER]"

# --- resolve to absolute path we intend to place in sudoers ---
resolve_path() {
  local inp="$1" found abs
  if [[ "$inp" == */* ]]; then
    abs="$(realpath -e -- "$inp")" || return 1
  else
    found="$(command -v -- "$inp" || true)" || true
    [[ -n "$found" ]] || return 1
    abs="$(realpath -e -- "$found")" || return 1
  fi
  printf '%s\n' "$abs"
}

map_local_orig_to_local() {
  # If abs path begins with /usr/local.orig/, rewrite to /usr/local/<rest>
  local p="$1"
  case "$p" in
    /usr/local.orig/*)
      printf '/usr/local/%s\n' "${p#/usr/local.orig/}"
      ;;
    *)
      printf '%s\n' "$p"
      ;;
  esac
}

abs="$(resolve_path "$cmd")" || die "Command not found/resolvable: $cmd"
mapped="$(map_local_orig_to_local "$abs")"

# Ensure mapped target exists & is executable (prevents granting dead path)
[[ -x "$mapped" ]] || die "Mapped command does not exist or is not executable: $mapped"

drop="/etc/sudoers.d/confer-${user}"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
umask 022

# Start with existing, drop any duplicates for our exact path
if [[ -e "$drop" ]]; then
  grep -v -F -- "NOPASSWD: ${mapped}" "$drop" > "$tmp" || true
else
  {
    echo "# Managed by h0-root-confer / h0-root-revoke"
    echo "# One command per line grants passwordless sudo for that exact path."
  } > "$tmp"
fi

# Append the grant
echo "${user} ALL=(root) NOPASSWD: ${mapped}" >> "$tmp"

# Validate and install atomically
visudo -cf "$tmp" >/dev/null || die "visudo validation failed"
install -o root -g root -m 0440 "$tmp" "$drop"

echo "Granted ${user} passwordless sudo for: ${mapped}"
