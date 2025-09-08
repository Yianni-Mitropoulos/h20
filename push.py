#!/usr/bin/env python3
import argparse
import os
import sys
import shutil
import subprocess
from pathlib import Path

DEFAULT_REMOTE    = os.getenv("RCLONE_REMOTE", "hero-to-zero-webserver")
DEFAULT_WEB_FMT   = os.getenv("WEB_BASE_PATH_PATTERN", "/var/www/htdocs/{suite}")
DEFAULT_APT_FMT   = os.getenv("APT_BASE_PATH_PATTERN", "/var/www/htdocs/{suite}/apt")

def run(cmd, cwd=None):
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

def ensure_exists(path: Path, what: str):
    if not path.exists():
        sys.stderr.write(f"error: expected {what} at {path} but it does not exist\n")
        sys.exit(1)

def main():
    p = argparse.ArgumentParser(description="Build and push signed website + apt repo via rclone (/{suite}/ and /{suite}/apt).")
    p.add_argument("suite", nargs="?", choices=["stable","unstable"], default="unstable",
                   help="Which suite to deploy (default: unstable)")
    p.add_argument("--remote", default=DEFAULT_REMOTE, help="rclone remote name")
    p.add_argument("--web-pattern", default=DEFAULT_WEB_FMT,
                   help="remote dir pattern for website (default: /var/www/htdocs/{suite})")
    p.add_argument("--apt-pattern", default=DEFAULT_APT_FMT,
                   help="remote dir pattern for apt repo (default: /var/www/htdocs/{suite}/apt)")
    p.add_argument("--dry-run", action="store_true", help="preview changes only")
    p.add_argument("--no-progress", action="store_true", help="omit --progress in rclone")
    args = p.parse_args()

    suite = args.suite
    cwd = Path.cwd()

    # sanity
    if shutil.which("rclone") is None:
        sys.stderr.write("error: rclone not found in PATH\n")
        sys.exit(1)

    # --- Build pipeline ---
    # 1) Build unsigned site into website_target/
    run([sys.executable, "./build_website.py"])
    # 2) Build packages into package_target/ (your existing script)
    run([sys.executable, "./build_deb.py"])
    # 3) Build flat APT repo into apt_repo/<suite> (signed for both suites)
    run([sys.executable, "./build_apt_repo.py", suite])
    # 4) Build signed site into signed_website_target/ (uses keys in ./gpg_keys)
    run([sys.executable, "./build_signed_website.py", suite])

    # --- Local artifacts we will upload ---
    signed_site_src = cwd / "signed_website_target"
    apt_src         = cwd / "apt_repo" / suite
    ensure_exists(signed_site_src, "signed_website_target directory")
    ensure_exists(apt_src, f"apt_repo/{suite} directory")

    # rclone flags
    rflags = []
    if args.dry_run:
        rflags.append("--dry-run")
    if not args.no_progress:
        rflags.append("--progress")
    # exclude hidden files/dirs
    rflags += ["--exclude", ".*"]

    # Remote destinations
    remote_web_dir = args.web_pattern.format(suite=suite).rstrip("/")
    remote_apt_dir = args.apt_pattern.format(suite=suite).rstrip("/")
    remote_web = f"{args.remote}:{remote_web_dir}"
    remote_apt = f"{args.remote}:{remote_apt_dir}"

    # Create dirs (idempotent)
    run(["rclone", "mkdir", remote_web])
    run(["rclone", "mkdir", remote_apt])

    # Sync signed website -> /{suite}/
    run(["rclone", "sync", str(signed_site_src), remote_web] + rflags)

    # Sync apt repo -> /{suite}/apt/
    run(["rclone", "sync", str(apt_src), remote_apt] + rflags)

    print("\nPush complete.")
    print(f"Website URL: https://hero-to-zero.ch/{suite}/")
    print(f"APT URL:     https://hero-to-zero.ch/{suite}/apt/")
    print(f"(remote web) {remote_web}")
    print(f"(remote apt) {remote_apt}")
    print("\nTip: set a root redirect to /stable/index.html in httpd.conf or with a tiny meta-refresh index.html at the docroot.")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"\ncommand failed with exit code {e.returncode}\n")
        sys.exit(e.returncode)
