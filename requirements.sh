#!/usr/bin/env bash
# Install all dependencies needed to build .deb packages and manage an APT repo

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (e.g., sudo $0)"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt update
apt install --no-install-recommends \
  build-essential \
  debhelper \
  devscripts \
  dpkg-dev \
  fakeroot \
  lintian \
  reprepro \
  gnupg \
  apt-utils \
  rsync
