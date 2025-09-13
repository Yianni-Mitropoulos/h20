#!/usr/bin/env bash
set -euo pipefail

FILE="/etc/sysctl.d/50-overrides.conf"

usage() {
  cat <<USAGE
Usage:
  h0-sysctl enable  <label> [label ...]
  h0-sysctl disable <label> [label ...]
  h0-sysctl status  [label ...]

Examples:
  h0-sysctl enable ipv6 reduced-logging
  h0-sysctl disable userns
  h0-sysctl status
USAGE
}

normalize() {
  awk 'BEGIN{s=tolower(ARGV[1]); gsub(/^[[:space:]]+|[[:space:]]+$/,"",s); print s}' "$1"
}

require_file() {
  [[ -f "$FILE" ]] || { echo "Error: $FILE not found." >&2; exit 1; }
}

run_sysctl_system() {
  echo "Applying sysctl settings (sysctl --system)..."
  if command -v sysctl >/dev/null 2>&1; then
    if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
      if command -v sudo >/dev/null 2>&1; then
        sudo sysctl --system
      else
        echo "Warning: not root and sudo not available; skipping sysctl --system." >&2
        return 0
      fi
    else
      sysctl --system
    fi
  else
    echo "Warning: sysctl not found; skipping apply." >&2
  fi
}

do_status() {
  local labels_csv="${1:-}"
  awk -v want_labels="$labels_csv" '
  BEGIN{
    split(want_labels, tmp, ",");
    for (i in tmp) if (length(tmp[i])) want[tolower(tmp[i])]=1;
    in_section=0; curr="";
  }
  function get_label(line) {
    if (match(line, /^# *\[[^]]+\]/)) {
      x=substr(line, RSTART, RLENGTH);
      gsub(/^# *\[/,"",x); gsub(/\]$/,"",x);
      return tolower(x);
    }
    return "";
  }
  {
    if (match($0, /^# *\[[^]]+\]/)) {
      curr=get_label($0); in_section=1;
      if (!(curr in total)) total[curr]=0;
      next;
    }
    if (in_section && $0 ~ /=/) {
      total[curr]++
      if ($0 ~ /^[[:space:]]*#/) com[curr]++; else unc[curr]++;
    }
  }
  END{
    if (length(want_labels)>0) {
      for (k in want) {
        if (k in total) {
          status=(unc[k]>0 && com[k]==0)?"enabled":(com[k]>0 && unc[k]==0)?"disabled":"mixed";
          printf "%s\t%s\n", k, status;
        } else {
          printf "%s\tnot-found\n", k;
        }
      }
    } else {
      for (k in total) {
        status=(unc[k]>0 && com[k]==0)?"enabled":(com[k]>0 && unc[k]==0)?"disabled":"mixed";
        printf "%s\t%s\n", k, status;
      }
    }
  }' "$FILE"
}

apply_action() {
  local action="$1"; shift
  local csv=""
  for l in "$@"; do
    norm="$(normalize "$l")"
    csv="${csv:+$csv,}$norm"
  done

  awk -v action="$action" -v targets="$csv" '
  BEGIN{
    split(targets, arr, ",");
    for (i in arr) if (length(arr[i])) tgt[arr[i]]=1;
    in_target=0; curr="";
  }
  function get_label(line) {
    if (match(line, /^# *\[[^]]+\]/)) {
      x=substr(line, RSTART, RLENGTH);
      gsub(/^# *\[/,"",x); gsub(/\]$/,"",x);
      return tolower(x);
    }
    return "";
  }
  function comment_line(s) {
    if (s ~ /^[[:space:]]*#/) sub(/^[[:space:]]*# */,"# ",s);
    else sub(/^[[:space:]]*/,"&# ",s);
    return s;
  }
  function uncomment_line(s) {
    sub(/^[[:space:]]*#?[[:space:]]*/,"",s);
    return s;
  }
  {
    if (match($0, /^# *\[[^]]+\]/)) {
      curr=get_label($0); in_target=(curr in tgt);
      print; next;
    }
    if (in_target && $0 ~ /=/) {
      if (action=="enable") { print uncomment_line($0); next }
      if (action=="disable") { print comment_line($0); next }
    }
    print
  }' "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"

  echo "Updated $FILE"
  echo
  echo "Status for requested labels:"
  do_status "$csv"
  echo
  run_sysctl_system
}

main() {
  [[ $# -gt 0 ]] || { usage; exit 1; }
  cmd="$1"; shift || true
  require_file
  case "$cmd" in
    enable|disable)
      [[ $# -gt 0 ]] || { echo "Need labels"; exit 1; }
      apply_action "$cmd" "$@"
      ;;
    status)
      if [[ $# -gt 0 ]]; then
        local csv=""; for l in "$@"; do norm="$(normalize "$l")"; csv="${csv:+$csv,}$norm"; done
        do_status "$csv"
      else
        do_status
      fi
      ;;
    *) usage; exit 1;;
  esac
}

main "$@"
