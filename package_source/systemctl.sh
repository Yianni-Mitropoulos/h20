#!/usr/bin/env bash
# Helper that manages /etc/h0-systemctl-list and masks/unmasks immediately.
# Expansion rules:
#   mask foo            -> foo.service + foo.socket
#   mask foo.service    -> foo.service
#   mask foo bar.socket -> foo.service, foo.socket, bar.socket
#   unmask foo.socket bar -> foo.socket, bar.service, bar.socket
set -euo pipefail

LIST_FILE=${LIST_FILE:-/etc/h0-systemctl-list}
EDITOR_BIN=${EDITOR:-nano}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Please run as root (sudo $0 ...)" >&2
    exit 1
  fi
}

ensure_list() {
  if [[ ! -e "$LIST_FILE" ]]; then
    install -o root -g root -m 0644 /dev/null "$LIST_FILE"
  fi
}

# Expand tokens into explicit .service/.socket names (no validation here).
expand_for_mask() {
  local t
  for t in "$@"; do
    case "$t" in
      *.service|*.socket) printf '%s\n' "$t" ;;
      *)                  printf '%s.service\n' "$t"; printf '%s.socket\n' "$t" ;;
    esac
  done
}

expand_for_unmask() {
  local t
  for t in "$@"; do
    case "$t" in
      *.service|*.socket) printf '%s\n' "$t" ;;
      *)                  printf '%s.service\n' "$t"; printf '%s.socket\n' "$t" ;;
    esac
  done
}

list_normalize_unique() {
  # Normalize LIST_FILE content: strip comments/space, keep only explicit units, sort -u
  local tmp
  tmp=$(mktemp)
  sed -E 's/[[:space:]]+#.*$//' "$LIST_FILE" \
  | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' \
  | awk 'NF' \
  | grep -E '^[A-Za-z0-9@:._-]+\.(service|socket)$' \
  | sort -u >"$tmp"
  install -o root -g root -m 0644 "$tmp" "$LIST_FILE"
  rm -f "$tmp"
}

add_units_to_list() {
  local tmp
  tmp=$(mktemp)
  cat "$LIST_FILE" >"$tmp" || true
  printf '%s\n' "$@" >>"$tmp"
  sed -E 's/[[:space:]]+#.*$//' "$tmp" \
  | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' \
  | awk 'NF' \
  | grep -E '^[A-Za-z0-9@:._-]+\.(service|socket)$' \
  | sort -u >"$tmp.sorted"
  install -o root -g root -m 0644 "$tmp.sorted" "$LIST_FILE"
  rm -f "$tmp" "$tmp.sorted"
}

remove_units_from_list() {
  # Remove exact matches for provided explicit units
  local tmp
  tmp=$(mktemp)
  # Build regex for exact matches
  local re='^('
  local first=1
  local u
  for u in "$@"; do
    local esc
    esc=$(printf '%s' "$u" | sed -E 's/[][(){}.^$|*+?]/\\&/g')
    if (( first )); then re+="$esc"; first=0; else re+="|$esc"; fi
  done
  re+=')$'
  awk -v pat="$re" '
    BEGIN{skip=0}
    {
      line=$0
      gsub(/[ \t]+#.*$/,"",line)     # strip trailing comments
      gsub(/^[ \t]+|[ \t]+$/,"",line) # trim
      if (line ~ pat) next
      print $0
    }
  ' "$LIST_FILE" >"$tmp"
  install -o root -g root -m 0644 "$tmp" "$LIST_FILE"
  rm -f "$tmp"
  list_normalize_unique
}

mask_now() {
  local u
  for u in "$@"; do systemctl mask "$u" || true; done
}

unmask_now() {
  local u
  for u in "$@"; do systemctl unmask "$u" || true; done
}

usage() {
  cat >&2 <<'EOF'
Usage:
  h0-systemctl                          # open /etc/h0-systemctl-list in $EDITOR (nano)
  h0-systemctl mask <units...>          # expand + mask now + add explicit units to list
  h0-systemctl unmask <units...>        # expand + unmask now + remove explicit units from list

Examples:
  h0-systemctl mask foo
  h0-systemctl mask foo.service bar.socket
  h0-systemctl unmask foo.socket bar
EOF
  exit 1
}

main() {
  require_root
  ensure_list

  if [[ $# -eq 0 ]]; then
    "$EDITOR_BIN" "$LIST_FILE"
    exit 0
  fi

  local cmd="$1"; shift || true
  case "$cmd" in
    mask)
      (( $# > 0 )) || usage
      mapfile -t expanded < <(expand_for_mask "$@")
      # keep only explicit units and de-dup
      mapfile -t units < <(printf '%s\n' "${expanded[@]}" \
        | grep -E '^[A-Za-z0-9@:._-]+\.(service|socket)$' \
        | sort -u)
      mask_now "${units[@]}"
      add_units_to_list "${units[@]}"
      ;;
    unmask)
      (( $# > 0 )) || usage
      mapfile -t expanded < <(expand_for_unmask "$@")
      mapfile -t units < <(printf '%s\n' "${expanded[@]}" \
        | grep -E '^[A-Za-z0-9@:._-]+\.(service|socket)$' \
        | sort -u)
      unmask_now "${units[@]}"
      remove_units_from_list "${units[@]}"
      ;;
    *)
      usage ;;
  esac
}

main "$@"
