#!/usr/bin/env bash
# Protect common user-edited dotfiles by giving them to root, so they require
# sudo to edit.

set -euo pipefail

# Dotfiles to protect (typically edited with CLI editors)
DOTFILES=(
  ".bashrc"
  ".bash_profile"
  ".profile"
  ".zshrc"
  ".zprofile"
  ".zlogin"
  ".kshrc"
  ".inputrc"
  ".pam_environment"
  ".xsession"
  ".xinitrc"
)

SSH_AUTH_KEYS=".ssh/authorized_keys"

# Find "human" users: UID >= 1000, not 'nobody', with a real home directory
get_human_users() {
  getent passwd | awk -F: '($3 >= 1000) && ($1 != "nobody") {print $1":"$6}'
}

is_sensitive() {
  # Slightly tighter perms for certain files
  local base="$1"
  case "$base" in
    ".pam_environment") return 0 ;;
    *) return 1 ;;
  esac
}

protect_file() {
  local path="$1" perm="$2"

  # Skip symlinks; only operate on regular files
  [[ -L "$path" ]] && { echo "  - Skipping symlink $path"; return; }
  [[ -f "$path" ]] || { return; }

  chown root:root "$path"
  chmod "$perm" "$path"
  echo "  - Set root:root $perm on $path"
}

protect_user() {
  local user="$1" home="$2"
  echo "==> Hardening $user ($home)"

  # Ensure ~/.ssh directory is tight and owned by the user
  if [[ -d "$home/.ssh" ]]; then
    chown "$user:$user" "$home/.ssh"
    chmod 700 "$home/.ssh"
    echo "  - Ensured $home/.ssh is $user:$user 700"
  fi

  # Regular dotfiles
  for f in "${DOTFILES[@]}"; do
    local p="$home/$f"
    if [[ -f "$p" && ! -L "$p" ]]; then
      local perm="0644"
      if is_sensitive "$f"; then perm="0600"; fi
      protect_file "$p" "$perm"
    fi
  done

  # authorized_keys (if present)
  local ak="$home/$SSH_AUTH_KEYS"
  if [[ -f "$ak" && ! -L "$ak" ]]; then
    # sshd accepts root-owned authorized_keys as long as it isn't group/other writable
    protect_file "$ak" "0600"
    # Re-tighten ~/.ssh just in case
    if [[ -d "$home/.ssh" ]]; then chmod 700 "$home/.ssh"; fi
  fi
}

main() {
  local found=0
  while IFS=: read -r user home; do
    [[ -d "$home" ]] || continue
    protect_user "$user" "$home"
    found=1
  done < <(get_human_users)

  if [[ $found -eq 0 ]]; then
    echo "No target users found."
  else
    echo "Done."
  fi
}

# Must run as root
if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must be run with sudo/root." >&2
  exit 1
fi

main
