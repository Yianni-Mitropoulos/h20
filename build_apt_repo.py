#!/usr/bin/env python3
import os, pathlib, shutil, subprocess, sys

# --- CONFIGURABLE CONSTANTS ---
CODENAME   = "bookworm"              # Debian/Ubuntu codename
COMPONENT  = "main"
PKG_DIR    = pathlib.Path("package_target")
REPO_BASE  = pathlib.Path("apt_repo")
GPG_KEY    = "ABCDEF1234567890"      # your key ID / fingerprint / email
# --------------------------------

def sh(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, **kw)

def dpkg_field(deb, field):
    out = subprocess.check_output(["dpkg-deb", "-f", str(deb), field], text=True)
    return out.strip()

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("stable","unstable"):
        print(f"Usage: {sys.argv[0]} stable|unstable", file=sys.stderr)
        sys.exit(1)
    suite = sys.argv[1]

    if not PKG_DIR.exists():
        print(f"missing {PKG_DIR}", file=sys.stderr); sys.exit(1)

    repo_root = REPO_BASE / suite
    if repo_root.exists():
        shutil.rmtree(repo_root)
    (repo_root / "pool" / COMPONENT).mkdir(parents=True, exist_ok=True)

    # copy .deb files into pool
    archs = set()
    for deb in PKG_DIR.glob("*.deb"):
        pkg  = dpkg_field(deb, "Package")
        arch = dpkg_field(deb, "Architecture")
        archs.add(arch)
        pool_dir = repo_root / "pool" / COMPONENT / pkg[0] / pkg
        pool_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(deb, pool_dir / deb.name)

    if not archs:
        print("no .deb files in package_target/", file=sys.stderr)
        sys.exit(1)

    # generate Packages files
    for arch in archs:
        bin_dir = repo_root / "dists" / CODENAME / COMPONENT / f"binary-{arch}"
        bin_dir.mkdir(parents=True, exist_ok=True)
        with (bin_dir / "Packages").open("w") as out:
            subprocess.check_call(
                ["dpkg-scanpackages", "--arch", arch, str(repo_root / "pool" / COMPONENT)],
                stdout=out
            )
        sh(["gzip", "-9f", str(bin_dir / "Packages")])

    # generate Release
    dists_dir = repo_root / "dists" / CODENAME
    release_path = dists_dir / "Release"
    with release_path.open("w") as out:
        subprocess.check_call(["apt-ftparchive", "release", "."], cwd=dists_dir, stdout=out)

    # prepend metadata
    meta = [
        f"Origin: h0 Project",
        f"Label: h0 APT",
        f"Suite: {suite}",
        f"Codename: {CODENAME}",
        f"Components: {COMPONENT}",
        f"Architectures: {' '.join(sorted(archs))}",
        "Description: Minimal repo for h0",
        ""
    ]
    release_path.write_text("\n".join(meta) + release_path.read_text())

    if suite == "stable":
        # ask user for passphrase
        import getpass
        pw = getpass.getpass(f"GPG passphrase for key {GPG_KEY}: ")

        env = os.environ.copy()
        gpg_base = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
                    "--passphrase", pw, "-u", GPG_KEY]

        cwd = os.fspath(dists_dir)
        sh(gpg_base + ["-abs", "-o", "Release.gpg", "Release"], cwd=cwd, env=env)
        sh(gpg_base + ["--clearsign", "-o", "InRelease", "Release"], cwd=cwd, env=env)

        pub = subprocess.check_output(["gpg", "--export", "-a", GPG_KEY])
        (repo_root / "YOURREPO.gpg").write_bytes(pub)

        print(f"Stable repo built and signed at {repo_root}")
    else:
        print(f"Unstable repo built (unsigned) at {repo_root}")

if __name__ == "__main__":
    main()
