sudo tee /etc/modprobe.d/h0-blacklist.conf > /dev/null <<'EOF'
# Target: ordinary AppVMs (no PCI passthrough)
# Keep Xen PV frontends: xen-blkfront, xen-netfront, xen-kbdfront, xen-fbfront
# WARNING: Do NOT use this template for sys-net or sys-usb; it will break them.

###############################################################################
# Networking (physical NICs; AppVMs use xen-netfront)
blacklist e1000
blacklist e1000e
blacklist r8169
blacklist r8168
blacklist atl1c
blacklist tg3
blacklist sky2
blacklist r8152

# Wi-Fi chipsets (AppVMs don't see real Wi-Fi)
blacklist iwlwifi
blacklist ath9k
blacklist ath10k_pci
blacklist brcmsmac
blacklist b43
blacklist rt2800pci
blacklist rt2800usb

###############################################################################
# Bluetooth
blacklist btusb
blacklist btrtl
blacklist btintel
blacklist btbcm
blacklist bluetooth

###############################################################################
# USB mass-storage & printer/scanner paths
blacklist usb_storage
blacklist uas
blacklist usblp
blacklist lp
blacklist parport
blacklist parport_pc

###############################################################################
# Audio (AppVMs don’t need hardware sound)
blacklist snd_hda_intel
blacklist snd_hda_codec
blacklist snd_usb_audio

###############################################################################
# Cameras / video capture (V4L2)
blacklist uvcvideo
blacklist gspca_main
blacklist videodev

###############################################################################
# HID (keyboards/mice/gamepads)
# Safe in AppVMs that never get HID USB attached. Remove if you ever attach one.
blacklist usbhid
blacklist hid_generic
blacklist hid_lenovo
blacklist hid_logitech_hidpp
blacklist hid_logitech_dj
blacklist hid_apple
blacklist hid

###############################################################################
# Legacy/exotic external buses
blacklist firewire-core
blacklist firewire-ohci
blacklist firewire-sbp2
blacklist thunderbolt
blacklist pcmcia
blacklist yenta_socket

###############################################################################
# Intel ME interface (not useful in AppVMs)
blacklist mei
blacklist mei_me

###############################################################################
# USB serial/modem classes (if you never attach them)
blacklist cdc_acm
blacklist usbserial
blacklist cp210x
blacklist ftdi_sio

###############################################################################
# Block creating encrypted devices INSIDE the AppVM (Dom0 handles the system LUKS)
blacklist dm_crypt
EOF