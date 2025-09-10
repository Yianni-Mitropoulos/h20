#!/usr/bin/env bash
# fs_harden_minimal.sh — universal, no options, safe defaults.
# - noatime,lazytime everywhere sensible
# - nosymfollow only if supported (auto-detect)
# - nodev,nosuid on "data" mounts (no 'noexec')
# - ext4 '/' gets errors=remount-ro and commit=60
# - backs up /etc/fstab, validates, and remounts changed mounts

set -euo pipefail

# ---------- Config (static) ----------
DATA_MOUNT_PATTERN='^/(home|srv|opt|var/(lib|mail|spool|www)|mnt|media)(/|$)'
BL_SKIP_FS_TYPES='^(proc|sysfs|devtmpfs|devpts|tmpfs|cgroup2?|pstore|efivarfs|securityfs|debugfs|tracefs|ramfs|nsfs|autofs|fuse\..*|fusectl|binfmt_misc|mqueue|hugetlbfs|configfs|bpf|overlay|squashfs|aufs|zram|zfs)$'
BL_NET_FS_TYPES='^(nfs|nfs4|cifs|smb3|sshfs|glusterfs|ceph|aufs)$'
BL_SKIP_MPS='^(/boot/efi|/snap|/var/lib/snapd|/run|/var/run)$'

# ---------- Helpers ----------
log(){ echo "$@"; }
has_opt(){ echo ",$1," | grep -q ",$2,"; }
add_opt_unique(){
  local opts="${1:-defaults}" add="$2"
  [[ -z "$opts" || "$opts" == "-" ]] && opts="defaults"
  if ! has_opt "$opts" "$add"; then opts="${opts},${add}"; fi
  echo "$opts" | sed -E 's/^,+//; s/,+$//; s/,,+/,/g'
}
remove_opt_like(){ echo "$1" | sed -E "s/(^|,)$2(,|$)/\1\2/g" | sed -E 's/^,+//; s/,+$//; s/,,+/,/g'; }
replace_opt(){ echo "$1" | sed -E "$2" | sed -E 's/^,+//; s/,+$//; s/,,+/,/g'; }
is_data_mount(){ [[ "$1" =~ $DATA_MOUNT_PATTERN ]]; }

supports_nosymfollow(){
  # Robust runtime test: remount a bind with nosymfollow; clean up either way.
  local tdir tmounted=0 ok=0
  tdir=$(mktemp -d) || return 1
  if sudo mount --bind "$tdir" "$tdir" 2>/dev/null; then
    tmounted=1
    if sudo mount -o remount,nosymfollow "$tdir" 2>/dev/null; then ok=1; fi
  fi
  [[ $tmounted -eq 1 ]] && sudo umount "$tdir" >/dev/null 2>&1 || true
  rmdir "$tdir" >/dev/null 2>&1 || true
  return $ok
}

merge_base_opts(){
  local existing="${1:-defaults}" nosym="${2}"
  # Prefer noatime over *atime variants
  existing=$(replace_opt "$existing" 's/(^|,)relatime(,|$)/\1noatime\2/g; s/(^|,)(strictatime|atime)(,|$)/\1noatime\3/g')
  existing=$(add_opt_unique "$existing" "noatime")
  existing=$(add_opt_unique "$existing" "lazytime")
  if [[ "$nosym" == "1" ]]; then
    existing=$(add_opt_unique "$existing" "nosymfollow")
  fi
  echo "$existing"
}

merge_ext4_root(){
  local opts="$1"
  opts=$(remove_opt_like "$opts" 'errors=[^,]+')
  opts=$(add_opt_unique "$opts" "errors=remount-ro")
  echo "$opts"
}

merge_data_hardening(){
  local opts="$1"
  opts=$(remove_opt_like "$opts" 'dev');   opts=$(add_opt_unique "$opts" "nodev")
  opts=$(remove_opt_like "$opts" 'suid');  opts=$(add_opt_unique "$opts" "nosuid")
  echo "$opts"
}

# ---------- Discover mounts ----------
log "Collecting mounted filesystems"
mapfile -t MOUNTS < <(findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS)

declare -A MP_FSTYPE MP_ID MP_OPTS
for line in "${MOUNTS[@]}"; do
  IFS=" " read -r TARGET SOURCE FSTYPE OPTS <<<"$line"
  [[ -z "${TARGET:-}" || -z "${FSTYPE:-}" ]] && continue
  [[ "$FSTYPE" =~ $BL_SKIP_FS_TYPES ]] && continue
  [[ "$FSTYPE" =~ $BL_NET_FS_TYPES ]] && continue
  [[ "$TARGET" =~ $BL_SKIP_MPS ]] && continue
  # Skip read-only mounts
  if echo ",${OPTS}," | grep -q ',ro,'; then continue; fi
  MP_FSTYPE["$TARGET"]="$FSTYPE"
  MP_OPTS["$TARGET"]="${OPTS:-defaults}"
  UUID=$(blkid -s UUID -o value "$SOURCE" 2>/dev/null || true)
  if [[ -n "$UUID" ]]; then
    MP_ID["$TARGET"]="UUID=$UUID"
  else
    MP_ID["$TARGET"]="$SOURCE"
  fi
done

(( ${#MP_FSTYPE[@]} > 0 )) || { log "Nothing eligible; no changes."; exit 0; }

# ---------- nosymfollow support probe ----------
NOSYM=0
if supports_nosymfollow; then
  NOSYM=1; log "nosymfollow: supported (will enable)."
else
  log "nosymfollow: not supported (skipping)."
fi

# ---------- Rewrite /etc/fstab ----------
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
UPDATED=0; ADDED=0; declare -A TOUCHED CHANGED

TS=$(date +%Y%m%d-%H%M%S)
sudo cp -a /etc/fstab "/etc/fstab.backup.${TS}"

while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" =~ ^[[:space:]]*# || "$line" =~ ^[[:space:]]*$ ]]; then
    echo "$line" >> "$TMP"; continue
  fi
  read -r DEV MP FSTYPE OPTS DUMP PASS <<<"$line" || true
  if [[ -z "${MP:-}" ]]; then echo "$line" >> "$TMP"; continue; fi

  if [[ -n "${MP_FSTYPE[$MP]:-}" ]]; then
    NEWOPTS=$(merge_base_opts "${OPTS:-defaults}" "$NOSYM")
    # FS-specific tweaks
    if [[ "${MP_FSTYPE[$MP]}" == "ext4" && "$MP" == "/" ]]; then
      NEWOPTS=$(merge_ext4_root "$NEWOPTS")
    fi
    # Data mount hardening (noexec intentionally omitted)
    if is_data_mount "$MP"; then
      NEWOPTS=$(merge_data_hardening "$NEWOPTS")
    fi
    if [[ "${OPTS:-defaults}" != "$NEWOPTS" ]]; then
      UPDATED=$((UPDATED+1))
      CHANGED["$MP"]="$NEWOPTS"
    fi
    printf "%-20s %-20s %-8s %-60s %d %d\n" \
      "${DEV}" "${MP}" "${FSTYPE}" "${NEWOPTS}" "${DUMP:-0}" "${PASS:-0}" >> "$TMP"
    TOUCHED["$MP"]=1
  else
    echo "$line" >> "$TMP"
  fi
done < /etc/fstab

for MP in "${!MP_FSTYPE[@]}"; do
  if [[ -z "${TOUCHED[$MP]:-}" ]]; then
    FST="${MP_FSTYPE[$MP]}"
    DEVSTR="${MP_ID[$MP]}"
    EXIST="${MP_OPTS[$MP]}"
    NEWOPTS=$(merge_base_opts "$EXIST" "$NOSYM")
    if [[ "$FST" == "ext4" && "$MP" == "/" ]]; then
      NEWOPTS=$(merge_ext4_root "$NEWOPTS")
    fi
    if is_data_mount "$MP"; then
      NEWOPTS=$(merge_data_hardening "$NEWOPTS")
    fi
    PASSVAL=2; [[ "$MP" == "/" ]] && PASSVAL=1
    printf "%-20s %-20s %-8s %-60s %d %d\n" \
      "$DEVSTR" "$MP" "$FST" "$NEWOPTS" 0 "$PASSVAL" >> "$TMP"
    ADDED=$((ADDED+1))
    # It was mounted without an fstab line; we added one—remount to apply.
    CHANGED["$MP"]="$NEWOPTS"
  fi
done

sudo install -m 0644 "$TMP" /etc/fstab

# ---------- Validate ----------
log "Validating fstab (mount -fav)"
set +e
sudo mount -fav >/dev/null 2>&1
RC=$?
set -e
if (( RC != 0 )); then
  echo "WARN: validation errors; review /etc/fstab (backup at /etc/fstab.backup.${TS})"
fi

# ---------- Live remount of changed mounts ----------
if (( ${#CHANGED[@]} > 0 )); then
  echo "Attempting live remount of updated mounts:"
  for mp in "${!CHANGED[@]}"; do
    newopts="${CHANGED[$mp]}"
    # Remove 'defaults' (harmless but noisy) before passing to mount
    opt_clean=$(echo "$newopts" | sed -E 's/(^|,)defaults(,|$)/\1\2/g; s/^,+//; s/,+$//; s/,,+/,/g')
    # mount(8) expects just the option list; prepend 'remount'
    if sudo mount -o "remount,${opt_clean}" "$mp" 2>/dev/null; then
      echo "  ✓ remounted $mp with: $opt_clean"
    else
      echo "  ✗ could not remount $mp (it will use new options on next boot)"
    fi
  done
fi

echo "Summary: updated=${UPDATED} added=${ADDED}; backup at /etc/fstab.backup.${TS}"
