#!/usr/bin/env bash
# Purges a wide range of packages that aren't needed in the ward.

# Remove core networking stack and related tools
until sudo apt purge -y network-manager* wpasupplicant ifupdown avahi* isc-dhcp-client isc-dhcp-common modemmanager ppp; do sleep 1; done

# Remove more network utilities and rsync
until sudo apt purge -y dnsutils iproute2 iputils-ping rsync; do sleep 1; done

# Remove netbase (low-level network data, optional)
until sudo apt purge -y netbase; do sleep 1; done

# Remove printing subsystem and color management
until sudo apt purge -y cups* printer-driver* system-config-printer sane* colord; do sleep 1; done

# Remove Bluetooth stack and modem tools
until sudo apt purge -y bluez* modemmanager rfkill; do sleep 1; done

# Remove network sharing and legacy services (SMB/NFS/RPC/FTP/Telnet/SSH)
until sudo apt purge -y samba* nfs-common rpcbind rpcsvc-proto ftp telnet ssh openssh-server openssh-client; do sleep 1; done

# Remove audio support
until sudo apt purge -y pulseaudio alsa-utils; do sleep 1; done

# Remove video/audio/media players
until sudo apt purge -y vlc* mplayer* ffmpeg*; do sleep 1; done

# Clean up
until sudo apt autoremove -y --purge; do sleep 1; done
until sudo apt clean; do sleep 1; done
echo 'Purge complete.'