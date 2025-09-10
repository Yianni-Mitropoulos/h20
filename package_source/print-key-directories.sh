#!/usr/bin/env bash

echo "domU"
echo "  /etc/local.orig/usr/  If this is a TemplateVM, you can put scripts in here and they'll persist and be inherited."
echo "  /etc/local/usr/       If this is an AppVM, you can put scripts in here and they'll persist."
echo "  /etc/sysctl.d/        Edit OS configurations"
echo "dom0"
echo "  /etc/qubes/policy.d/  Allows you to control QubesOS RPC policies."