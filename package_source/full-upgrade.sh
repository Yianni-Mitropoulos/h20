#!/usr/bin/env bash
# A one liner for updating your system.

set -euo pipefail

echo "Updating package metadata."
sudo apt update

echo "Performing a full upgrade."
sudo apt full-upgrade

echo "Removing packages that were automatically installed to satisfy dependencies but are no longer needed."
sudo apt autoremove

echo "Clearing out the local cache of retrieved package files."
sudo apt clean

echo "Success!"