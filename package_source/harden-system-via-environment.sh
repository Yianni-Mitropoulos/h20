#!/usr/bin/env bash
set -euo pipefail

# Overwrite /etc/environment with hardened defaults
sudo tee /etc/environment >/dev/null <<'EOF'
###############################################################################
# PATH: minimal, trusted search path. No '.' or user-writable dirs.
###############################################################################
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

###############################################################################
# glibc malloc hardening:
# - MALLOC_CHECK_=3: warn + abort on heap corruption.
# - MALLOC_PERTURB_=153: fill alloc/free with 0x99 to expose UAF/uninit bugs.
###############################################################################
MALLOC_CHECK_="3"
MALLOC_PERTURB_="153"

###############################################################################
# Library preload & search path neutralization:
# Prevent accidental or malicious library injection via inherited env vars.
# Explicit per-service or per-user overrides are still possible.
###############################################################################
LD_PRELOAD=""
LD_LIBRARY_PATH=""
LD_AUDIT=""

###############################################################################
# Proxy variables:
# Prevent a low-privilege user from tricking a high-privilege command into
# using an untrusted proxy (MITM/exfil) via inherited env vars.
# Configure proxies explicitly per-tool (apt, curlrc, systemd units) instead.
###############################################################################
http_proxy=""
https_proxy=""
ftp_proxy=""
no_proxy="localhost,127.0.0.1,::1"

###############################################################################
# Language/runtime hardening:
# Python:
# - PYTHONHASHSEED=random: randomize hash seed to mitigate hash-collision DoS.
# - PYTHONNOUSERSITE=1: ignore user site-packages to reduce code-injection risk.
###############################################################################
PYTHONHASHSEED="random"
PYTHONNOUSERSITE="1"

###############################################################################
# Pagers:
# - LESSSECURE=1: 'less' will not execute shell commands (!, |) — safer when
#   privileged tools page output through less.
###############################################################################
LESSSECURE="1"

###############################################################################
# Ruby:
# - --disable-gems: avoid loading user gem paths by default (reduces injection).
###############################################################################
RUBYOPT="--disable-gems"

EOF

echo "Success!"
echo "Hardened /etc/environment written."
