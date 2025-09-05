#!/usr/bin/env python3
import os, pathlib, subprocess, sys, time, shutil

# --- CONFIGURABLE CONSTANTS ---
REMOTE      = "you@openbsd-host"         # SSH remote
REMOTE_ROOT = "/var/www/htdocs"          # web root on remote
WEBSITE_SRC = pathlib.Path("website_target")
APT_BASE    = pathlib.Path("apt_repo")
STAGING_BASE= pathlib.Path("deploy_stage")
RCLONE_BIN  = "rclone"
# --------------------------------

def sh(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, **kw)

def hardlink_tree(src: pathlib.Path, dst: pathlib.Path):
    for p in src.rglob("*"):
        if p.is_file():
            t = dst / p.relative_to(src)
            if not t.exists():
                t.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(p, t)   # hardlink
                except OSError:
                    shutil.copy2(p, t)   # fallback

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("stable","unstable"):
        print(f"Usage: {sys.argv[0]} stable|unstable", file=sys.stderr)
        sys.exit(1)

    suite = sys.argv[1]
    apt_src = APT_BASE / suite
    staging_dir = STAGING_BASE / suite

    if not WEBSITE_SRC.exists() or not apt_src.exists():
        print("Missing website_target/ or apt_repo/<suite>/; run build steps first", file=sys.stderr)
        sys.exit(1)

    # fresh staging dir
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    # hardlink/copy content
    hardlink_tree(WEBSITE_SRC, staging_dir)
    hardlink_tree(apt_src, staging_dir / "apt")

    # release name
    stamp = time.strftime("%Y%m%d-%H%M%S")
    remote_release = f"{REMOTE_ROOT}/{suite}/releases/{stamp}"

    # ensure releases dir exists
    sh(["ssh", REMOTE, "mkdir", "-p", f"{REMOTE_ROOT}/{suite}/releases"])

    # rclone sync
    sh([RCLONE_BIN, "copy", "--copy-links", "--delete-during",
        str(staging_dir) + "/", f"{REMOTE}:{remote_release}"])

    # update current symlink
    sh(["ssh", REMOTE, f"ln -sfn {remote_release} {REMOTE_ROOT}/{suite}/current"])

    print(f"Deployed {suite} to {REMOTE}:{remote_release} and updated {suite}/current")

if __name__ == "__main__":
    main()
