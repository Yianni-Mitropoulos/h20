#!/usr/bin/env bash
# Installs the locales package if not available, and guides the user through
# selecting their locale.
sudo apt update
sudo apt install locales
sudo dpkg-reconfigure locales
