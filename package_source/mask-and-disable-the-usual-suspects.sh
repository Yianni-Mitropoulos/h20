#!/usr/bin/env bash
# Disables and masks a variety of service units and socket units, reducing the
# attack surface.

set -euo pipefail

echo "Masking service units"
services=(
  NetworkManager
  network
  wicd
  wpa_supplicant
  bluetooth
  rfkill
  cups
  cups-browsed
  pcscd
  usbguard
  ModemManager
  avahi-daemon
  nfs-client
  nfs-common
  smb
  smbd
  rpcbind
  zeroconf
  nmbd
  chronyd
  ntpd
  systemd-timesyncd
  sshd
  telnetd
  rshd
  dnsmasq
  resolvconf
  dhclient
  firewalld
  openvpn
)
for SERVICE in "${services[@]}"; do
  sudo systemctl disable "$SERVICE.service" &> /dev/null;
  sudo systemctl mask "$SERVICE.service" &> /dev/null;
done

echo "Masking socket units"
sockets=(
  NetworkManager
  avahi-daemon
  systemd-udevd
)
for SOCKET in "${sockets[@]}"; do
  sudo systemctl disable "$SOCKET.socket" &> /dev/null;
  sudo systemctl mask "$SOCKET.socket" &> /dev/null;
done

echo "All listed services and sockets have been disabled and masked."