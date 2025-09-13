#!/usr/bin/env bash
# Maybe we should put everything in /etc/h0
# And every file we create becomes a symlink into there
echo "domU"
echo "  /etc/local.orig/usr/  If this is a TemplateVM, you can put scripts in here and they'll persist and be inherited."
echo "  /etc/local/usr/       If this is an AppVM, you can put scripts in here and they'll persist."
echo "  /etc/sysctl.d/    Sysctl configurations"
echo "  /etc/modprobe.d/  Kernel Module Blacklist"
echo "dom0"
echo "  /etc/qubes/policy.d/  Allows you to control QubesOS RPC policies."