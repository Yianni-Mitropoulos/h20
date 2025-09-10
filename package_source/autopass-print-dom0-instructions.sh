#!/usr/bin/env bash
# Simple explains how to set up dom0 permissions to facilitate autopass.

echo "In dom0:"
echo "Create /etc/qubes/policy.d/30-local-autopass.policy"
echo "Write the line 'local.SendDisposablePassword * * sys-passwords allow' into the aforementioned file."
echo "That's it."