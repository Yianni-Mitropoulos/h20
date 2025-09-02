#!/usr/bin/env bash
# h0-root-revoke: revoke passwordless sudo for ONE command previously granted
# Usage:
#   h0-root-revoke <command> [--user USER]
# Notes:
#   - Mirrors root-confer's resolution and /usr/local.orig → /usr/local mapping.
#   - Removes the exact entry; deletes the drop-in if empty.

set -euo pipefail

die() { echo "Error: $*" >&2; exit 1; }

if [[ $EUID -ne 0 ]]; then
  exec sudo -n -- "$0" "$@"
fi

user="${SUDO_USER:-${USER:-}}"
cmd=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) shift; [[ $# -gt 0 ]] || die "--user requires a value"; user="$1"; shift ;;
    -*)     die "Unknown option: $1" ;;
    *)      [[ -z "$cmd" ]] || die "Only one command may be revoked at a time"; cmd="$1"; shift ;;
  esac
done

[[ -n "$user" ]] || die "Could not determine target user"
[[ -n "$cmd"  ]] || die "Usage: h0-root-revoke <command> [--user USER]"

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
  local p="$1"
  case "$p" in
    /usr/local.orig/*) printf '/usr/local/%s\n' "${p#/usr/local.orig/}" ;;
    *)                 printf '%s\n' "$p" ;;
  esac
}

abs="$(resolve_path "$cmd")" || die "Command not found/resolvable: $cmd"
mapped="$(map_local_orig_to_local "$abs")"

drop="/etc/sudoers.d/confer-${user}"
[[ -e "$drop" ]] || { echo "No grant file for ${user} (${drop})"; exit 0; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

# Remove the exact grant line; also remove any legacy line using the .orig path
grep -v -F -- "NOPASSWD: ${mapped}" "$drop" | \
grep -v -F -- "NOPASSWD: ${abs}" > "$tmp" || true

visudo -cf "$tmp" >/dev/null || die "visudo validation failed"

if grep -qE '^[^#[:space:]]' "$tmp"; then
  install -o root -g root -m 0440 "$tmp" "$drop"
  echo "Revoked ${user} passwordless sudo for: ${mapped}"
else
  rm -f -- "$drop"
  echo "Revoked ${user} passwordless sudo for: ${mapped} (removed empty drop-in)"
fi
