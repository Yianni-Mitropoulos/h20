#!/usr/bin/env bash
# Persists noatime,lazytime via /etc/fstab for all mounted filesystems
# except those with FS types in the blacklist.

set -euo pipefail

echo "Collecting mounted filesystems"
# Blacklist: skip only pseudo/virtual/ephemeral FS
BL_SKIP_FS_TYPES='^(proc|sysfs|devtmpfs|devpts|tmpfs|cgroup2?|pstore|efivarfs|securityfs|debugfs|tracefs|ramfs|nsfs|autofs|fuse\..*|fusectl|binfmt_misc|mqueue|hugetlbfs|configfs|bpf|overlay|squashfs|aufs|swap)$'

mapfile -t MOUNTS < <(sudo findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS \
  | awk -v bl="$BL_SKIP_FS_TYPES" -F' ' '
      {
        tgt=$1; src=$2; typ=$3; opts=$4;
        if (typ ~ bl) next;   # blacklist only
        print tgt "|" src "|" typ "|" opts
      }')

if (( ${#MOUNTS[@]} == 0 )); then
  echo "Summary: nothing eligible; no changes made"
  exit 0
fi

# Build maps for later
declare -A MP_FSTYPE MP_ID
for line in "${MOUNTS[@]}"; do
  IFS="|" read -r TARGET SOURCE FSTYPE OPTS <<<"$line"
  MP_FSTYPE["$TARGET"]="$FSTYPE"
  UUID=$(sudo blkid -s UUID -o value "$SOURCE" 2>/dev/null || true)
  if [[ -n "$UUID" ]]; then
    MP_ID["$TARGET"]="UUID=$UUID"
  else
    MP_ID["$TARGET"]="$SOURCE"
  fi
done

merge_opts() {
  local existing="${1:-defaults}"
  if [[ -z "$existing" || "$existing" == "-" ]]; then existing="defaults"; fi
  existing=$(echo "$existing" \
    | sed -E 's/(^|,)relatime(,|$)/\1noatime\2/g; s/(^|,)(strictatime|atime)(,|$)/\1noatime\3/g')
  if ! echo ",$existing," | grep -q ',noatime,'; then existing="${existing},noatime"; fi
  if ! echo ",$existing," | grep -q ',lazytime,'; then existing="${existing},lazytime"; fi
  echo "$existing" | sed -E 's/^,+//; s/,+$//; s/,,+/,/g'
}

echo "Rewriting /etc/fstab to persist noatime,lazytime"
TMP=$(mktemp)
touch "$TMP"
UPDATED=0
ADDED=0
declare -A TOUCHED

# Pass 1: rewrite lines that match eligible mountpoints
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" =~ ^[[:space:]]*# || "$line" =~ ^[[:space:]]*$ ]]; then
    echo "$line" >> "$TMP"
    continue
  fi
  read -r DEV MP FSTYPE OPTS DUMP PASS <<<"$line" || true
  if [[ -z "${MP:-}" ]]; then
    echo "$line" >> "$TMP"
    continue
  fi
  if [[ -n "${MP_FSTYPE[$MP]:-}" ]]; then
    NEWOPTS=$(merge_opts "${OPTS:-defaults}")
    if [[ "${OPTS:-defaults}" != "$NEWOPTS" ]]; then UPDATED=$((UPDATED+1)); fi
    printf "%-20s %-15s %-8s %-40s %d %d\n" \
      "${DEV}" "${MP}" "${FSTYPE}" "${NEWOPTS}" "${DUMP:-0}" "${PASS:-0}" >> "$TMP"
    TOUCHED["$MP"]=1
  else
    echo "$line" >> "$TMP"
  fi
done < /etc/fstab

# Pass 2: add entries for eligible mounts missing in fstab
for MP in "${!MP_FSTYPE[@]}"; do
  if [[ -z "${TOUCHED[$MP]:-}" ]]; then
    FST="${MP_FSTYPE[$MP]}"
    DEVSTR="${MP_ID[$MP]}"
    NEWOPTS=$(merge_opts "defaults")
    PASSVAL=2; [[ "$MP" == "/" ]] && PASSVAL=1
    printf "%-20s %-15s %-8s %-40s %d %d\n" \
      "$DEVSTR" "$MP" "$FST" "$NEWOPTS" 0 "$PASSVAL" >> "$TMP"
    ADDED=$((ADDED+1))
  fi
done

sudo install -m 644 "$TMP" /etc/fstab
rm -f "$TMP"

echo "Validating fstab"
set +e
sudo mount -fav >/dev/null 2>&1
RC=$?
set -e
if (( RC != 0 )); then
  echo "  Validation reported errors; review /etc/fstab"
fi

echo "Summary: updated=${UPDATED} added=${ADDED}; changes will apply on next boot"
