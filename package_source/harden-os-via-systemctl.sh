#!/usr/bin/env bash
# Create /etc/h0-systemctl-list and a systemd unit that re-masks units at boot/shutdown,
# ordering it *before* qubes-gen-sudo-pw.service to avoid sudo password issues.
set -euo pipefail

LIST=/etc/h0-systemctl-list
UNIT=/etc/systemd/system/h0-systemctl.service
ENGINE=/usr/bin/h0-systemctl-impose-masks.sh
QUBES_SUDO_SERVICE=qubes-gen-sudo-pw.service

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Please run as root (sudo $0)" >&2
    exit 1
  fi
}

write_list() {
  cat >"$LIST" <<'EOF'
# h0-systemctl explicit unit list
# One unit per line; must end with .service or .socket

# Services
NetworkManager.service
network.service
wicd.service
wpa_supplicant.service
bluetooth.service
rfkill.service
cups.service
cups-browsed.service
pcscd.service
usbguard.service
ModemManager.service
avahi-daemon.service
nfs-client.service
nfs-common.service
smb.service
smbd.service
rpcbind.service
zeroconf.service
nmbd.service
chronyd.service
ntpd.service
systemd-timesyncd.service
sshd.service
telnetd.service
rshd.service
dnsmasq.service
resolvconf.service
dhclient.service
firewalld.service
openvpn.service

# Sockets
NetworkManager.socket
avahi-daemon.socket
systemd-udevd.socket
EOF

  chown root:root "$LIST"
  chmod 0644 "$LIST"
}

write_unit() {
  # We run very early and explicitly *before* qubes-gen-sudo-pw.service.
  # RemainAfterExit allows ExecStop= to run at shutdown as well.
  cat >"$UNIT" <<EOF
[Unit]
Description=Re-mask configured services and sockets (h0)
DefaultDependencies=no
Before=sysinit.target
Before=${QUBES_SUDO_SERVICE}
Conflicts=shutdown.target
Before=shutdown.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${ENGINE} apply
ExecStop=${ENGINE} apply

[Install]
WantedBy=sysinit.target
WantedBy=shutdown.target
EOF

  chown root:root "$UNIT"
  chmod 0644 "$UNIT"
}

main() {
  require_root

  if [[ ! -x "$ENGINE" ]]; then
    echo "ERROR: $ENGINE not found or not executable at ${ENGINE}." >&2
    echo "It should be installed by your package into /usr/bin." >&2
    exit 1
  fi

  write_list
  write_unit

  systemctl daemon-reload
  systemctl enable --now h0-systemctl.service
  # Apply immediately this first time
  "${ENGINE}" apply || true

  echo "Initialized:"
  echo "  - List:  $LIST (root-owned)"
  echo "  - Unit:  $UNIT (enabled; ordered before ${QUBES_SUDO_SERVICE})"
  echo "  - Engine applied now; will run at boot and shutdown"
}

main "$@"
