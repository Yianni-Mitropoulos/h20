#!/usr/bin/env bash
set -euo pipefail

# Usage: refresh_gpg_keys <suite>
[[ $# -eq 1 ]] || { echo "Usage: $0 <suite>"; exit 1; }
suite="$1"

read -s -p "Passphrase to protect the private key: " pass; echo

outdir="$(pwd)/gpg_keys"
mkdir -p "$outdir"
pub_out="$outdir/${suite}_gpg_key_public.asc"
priv_out="$outdir/${suite}_gpg_key_private.asc"

# Use a temporary keyring so we don't touch your main GPG setup
tmpgnupg="$(mktemp -d)"
trap 'rm -rf "$tmpgnupg"' EXIT
chmod 700 "$tmpgnupg"
export GNUPGHOME="$tmpgnupg"

uid="${suite} <${suite}@example.invalid>"

# Generate a minimal Ed25519 key, protected with the passphrase
gpg --batch --yes \
    --pinentry-mode loopback \
    --passphrase "$pass" \
    --quick-generate-key "$uid" ed25519 sign 0

# Export public and private keys (ASCII-armored), overwriting if present
gpg --batch --yes --armor --export "$uid" > "$pub_out"
gpg --batch --yes \
    --pinentry-mode loopback \
    --passphrase "$pass" \
    --armor --export-secret-keys "$uid" > "$priv_out"

chmod 600 "$priv_out"

echo "Wrote:"
echo "  $pub_out"
echo "  $priv_out"
