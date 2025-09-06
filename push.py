#!/usr/bin/env python3
import argparse
import os
import sys
import shutil
import subprocess
from pathlib import Path

DEFAULT_REMOTE = os.getenv("RCLONE_REMOTE", "hero-to-zero-webserver")
DEFAULT_WEB_BASE = os.getenv("WEB_BASE_PATH", "/var/www/htdocs")
DEFAULT_APT_BASE = os.getenv("APT_BASE_PATH", "/var/www/htdocs/apt")

def run(cmd, cwd=None):
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)

def ensure_exists(path: Path, what: str):
    if not path.exists():
        sys.stderr.write(f"error: expected {what} at {path} but it does not exist\n")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Build and push website + apt repo via rclone.")
    parser.add_argument("suite", nargs="?", choices=["stable", "unstable"], default="unstable",
                        help="Which suite to deploy (default: unstable)")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="rclone remote name")
    parser.add_argument("--web-base", default=DEFAULT_WEB_BASE, help="remote base path for website")
    parser.add_argument("--apt-base", default=DEFAULT_APT_BASE, help="remote base path for apt repo")
    parser.add_argument("--dry-run", action="store_true", help="preview changes only")
    parser.add_argument("--no-progress", action="store_true", help="omit --progress in rclone")
    args = parser.parse_args()

    suite = args.suite
    cwd = Path.cwd()

    # sanity: rclone present
    if shutil.which("rclone") is None:
        sys.stderr.write("error: rclone not found in PATH\n")
        sys.exit(1)

    # build steps
    run([sys.executable, "./build_website.py"])
    run([sys.executable, "./build_deb.py"])
    run([sys.executable, "./build_apt_repo.py", suite])

    # local artifacts
    website_src = cwd / "website_target"
    apt_src = cwd / "apt_repo" / suite
    ensure_exists(website_src, "website_target directory")
    ensure_exists(apt_src, f"apt_repo/{suite} directory")

    # rclone flags
    rclone_flags = []
    if args.dry_run:
        rclone_flags.append("--dry-run")
    if not args.no_progress:
        rclone_flags.append("--progress")
    # exclude hidden files/dirs
    rclone_flags += ["--exclude", ".*"]

    remote_web = f"{args.remote}:{args.web_base.rstrip('/')}/{suite}"
    remote_apt = f"{args.remote}:{args.apt_base.rstrip('/')}/{suite}"

    # create dirs (safe if they exist)
    run(["rclone", "mkdir", remote_web])
    run(["rclone", "mkdir", remote_apt])

    # sync website
    run(["rclone", "sync", str(website_src), remote_web] + rclone_flags)

    # sync apt repo
    run(["rclone", "sync", str(apt_src), remote_apt] + rclone_flags)

    print("\nPush complete.")
    print(f"Website:  https://hero-to-zero.ch/        (serves {suite})" if suite == "stable" else
          "Website:  https://hero-to-zero.ch/ (stable) and /unstable/ serves this push")
    print(f"APT repo: {remote_apt}")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"\ncommand failed with exit code {e.returncode}\n")
        sys.exit(e.returncode)
