#!/usr/bin/env python3
import argparse
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

KEYS_DIRNAME = "gpg_keys"

def run(cmd, *, env=None, input_bytes=None):
    print("+", " ".join(cmd))
    return subprocess.run(
        cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, input=input_bytes
    )

def ensure_tool(name: str):
    if shutil.which(name) is None:
        sys.stderr.write(f"error: required tool '{name}' not found in PATH\n")
        sys.exit(1)

def backup_if_exists(path: Path):
    if path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_suffix(path.suffix + f".bak.{ts}")
        path.replace(backup)
        print(f"Backed up existing {path.name} -> {backup.name}")

def main():
    ensure_tool("gpg")

    ap = argparse.ArgumentParser(
        description="Rebuild an armored GPG keypair for a suite; exports to ./gpg_keys/"
    )
    ap.add_argument("suite", nargs="?", choices=["stable", "unstable"], default="unstable",
                    help="suite to generate keys for (default: unstable)")
    ap.add_argument("--algo", default="ed25519",
                    help="primary key algorithm (default: ed25519)")
    ap.add_argument("--uid-name", default="h0 Signed Pages Key",
                    help='UID "Real Name" (default: h0 Signed Pages Key)')
    ap.add_argument("--uid-email", default=None,
                    help='UID email; default auto: h0-<suite>@example.invalid')
    args = ap.parse_args()

    suite = args.suite
    algo  = args.algo
    uid_email = args.uid_email or f"h0-{suite}@example.invalid"
    uid = f"{args.uid_name} ({suite}) <{uid_email}>"

    # Ask for passphrase (twice)
    pw1 = getpass.getpass(f"New passphrase for {suite} key: ")
    pw2 = getpass.getpass("Repeat passphrase: ")
    if pw1 != pw2:
        sys.stderr.write("error: passphrases do not match\n")
        sys.exit(1)
    if len(pw1) < 8:
        sys.stderr.write("warning: passphrase is short (<8 chars)\n")

    # Isolated GNUPGHOME
    gnupg_home = Path(tempfile.mkdtemp(prefix="gnupg-gen-"))
    try:
        os.chmod(gnupg_home, 0o700)
    except Exception:
        pass
    env = os.environ.copy()
    env["GNUPGHOME"] = str(gnupg_home)

    try:
        # Generate primary key (sign-capable). --quick-generate-key creates a cert/sign-capable primary.
        # No expiry ("0") for simplicity; adjust if you want rotation.
        run([
            "gpg", "--batch", "--yes",
            "--pinentry-mode", "loopback", "--passphrase", pw1,
            "--quick-generate-key", uid, algo, "sign", "0"
        ], env=env)

        # Get fingerprint
        out = run(["gpg", "--batch", "--with-colons", "--list-secret-keys"], env=env).stdout.decode()
        fprs = [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:")]
        if not fprs:
            sys.stderr.write("error: could not obtain key fingerprint\n")
            sys.exit(1)
        fpr = fprs[0]
        print(f"Fingerprint: {fpr}")

        # Prepare output paths
        keys_dir = Path.cwd() / KEYS_DIRNAME
        keys_dir.mkdir(parents=True, exist_ok=True)
        pub_out  = keys_dir / f"{suite}_gpg_key_public.asc"
        priv_out = keys_dir / f"{suite}_gpg_key_private.asc"

        # Backup existing files (if any)
        backup_if_exists(pub_out)
        backup_if_exists(priv_out)

        # Export public key (ASCII armored)
        pub_ascii = run(["gpg", "--armor", "--export", fpr], env=env).stdout
        pub_out.write_bytes(pub_ascii)
        print(f"Wrote {pub_out}")

        # Export secret key (ASCII armored, protected with the key's passphrase you set)
        # Note: export doesn’t prompt; the key material remains passphrase-protected.
        sec_ascii = run([
            "gpg", "--batch", "--yes",
            "--pinentry-mode", "loopback", "--passphrase", pw1,
            "--armor", "--export-secret-keys", fpr
        ], env=env).stdout
        priv_out.write_bytes(sec_ascii)
        print(f"Wrote {priv_out}")

        print("\nDone.")
        print("Use these with build_signed_website.py; it will import the private key and")
        print("unlock it using --pinentry-mode loopback + your passphrase.")
        print("\nExample:")
        print(f"  ./build_signed_website.py {suite}")

    except subprocess.CalledProcessError as e:
        sys.stderr.write("\ncommand failed:\n")
        sys.stderr.write(e.stderr.decode(errors="ignore"))
        sys.exit(e.returncode)
    finally:
        # Clean up the temporary GNUPGHOME
        shutil.rmtree(gnupg_home, ignore_errors=True)

if __name__ == "__main__":
    main()
