#!/usr/bin/env bash
# Installs passwd and passwordless sudo. Also ensures that disposables randomly
# generate their own custom passwords at startup, thereby reducing the blast
# radius in the event of a compromise. These custom passwords are sent to the
# sys-password qube via the local.SendDisposablePassword remote procedure call.
# You can set up sys-password by running `h0-autopass-setup-receiver`. You also
# have to allow the local.SendDisposablePassword RPC in dom0. Simply run
# `h0-autopass-print-dom0-instructions` if you'd like to see the details.

set -euo pipefail

VAULT_VM="sys-passwords"
SERVICE_NAME="local.SendDisposablePassword"

CONF="/etc/qubes-temp-sudo.conf"
HELPER="/usr/libexec/qubes/qubes-gen-sudo-pw"
UNIT="/etc/systemd/system/qubes-gen-sudo-pw.service"

echo "Installing prerequisites via apt..."
sudo apt update
sudo apt install --no-install-recommends passwd qubes-core-agent-passwordless-root

echo "Writing config to $CONF"
sudo tee "$CONF" >/dev/null <<EOF
VAULT_VM="$VAULT_VM"
SERVICE_NAME="$SERVICE_NAME"
PW_CHARSET='a-z'
PW_LEN=16
EOF
sudo chmod 0644 "$CONF"

echo "Installing helper to $HELPER"
sudo install -d -m 0755 /usr/libexec/qubes
sudo tee "$HELPER" >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
log(){ /usr/bin/logger -t qubes-gen-sudo-pw -- "$*"; }

# Only run in DisposableVMs; bail out if persistence is not "none"
if [ "$(qubesdb-read /qubes-vm-persistence 2>/dev/null || echo rw)" != "none" ]; then
  log "Not a DisposableVM, skipping password setup"
  exit 0
fi

# defaults if config absent
VAULT_VM_DEFAULT="sys-passwords"
SERVICE_NAME_DEFAULT="local.SendDisposablePassword"
PW_CHARSET_DEFAULT='a-z'
PW_LEN_DEFAULT=16

CONF="/etc/qubes-temp-sudo.conf"
[ -r "$CONF" ] && source "$CONF" || true
: "${VAULT_VM:=$VAULT_VM_DEFAULT}"
: "${SERVICE_NAME:=$SERVICE_NAME_DEFAULT}"
: "${PW_CHARSET:=$PW_CHARSET_DEFAULT}"
: "${PW_LEN:=$PW_LEN_DEFAULT}"

# 1) generate password (lowercase only), avoid pipefail on SIGPIPE
set +o pipefail
PW="$(/usr/bin/tr -dc "$PW_CHARSET" </dev/urandom | /usr/bin/head -c "$PW_LEN" || true)"
set -o pipefail
if [ -z "${PW:-}" ] || [ "${#PW}" -lt "$PW_LEN" ]; then
  log "password generation failed"; exit 1
fi

# 2) set for 'user' — Linux hashes automatically
printf 'user:%s\n' "$PW" | /usr/sbin/chpasswd || { log "chpasswd failed"; exit 1; }

# 3) ensure sudo prompts (strip NOPASSWD from qubes sudoers, if present)
if [ -f /etc/sudoers.d/qubes ]; then
  /bin/sed -i 's/\bNOPASSWD:\? *//g' /etc/sudoers.d/qubes || log "sudoers edit warning"
fi

# 4) send plaintext once to vault via qrexec (stdin only)
if ! printf '%s' "$PW" | /usr/bin/qrexec-client-vm "$VAULT_VM" "$SERVICE_NAME"; then
  log "qrexec send failed to $VAULT_VM/$SERVICE_NAME"
fi

unset PW
exit 0
EOF
sudo chmod 0755 "$HELPER"

echo "Installing systemd unit $UNIT"
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Generate temporary sudo password and send to sys-passwords
DefaultDependencies=no
After=qubes-misc-post.service qubes-qrexec-agent.service
Wants=qubes-qrexec-agent.service
Before=getty.target multi-user.target

[Service]
Type=oneshot
ExecStart=$HELPER

[Install]
WantedBy=multi-user.target
EOF

echo "Enabling service."
sudo systemctl daemon-reload
sudo systemctl enable qubes-gen-sudo-pw.service

echo "Success!"