#!/usr/bin/env python3
import os
import pathlib
import shutil
import subprocess
import sys
import getpass
import tempfile

# --- CONFIGURABLE CONSTANTS ---
COMPONENT    = "main"                         # kept for pool/ layout & metadata
PKG_DIR      = pathlib.Path("package_target")
REPO_BASE    = pathlib.Path("apt_repo")
KEYS_DIR     = pathlib.Path("gpg_keys")
PRIVKEY_TPL  = "{suite}_gpg_key_private.asc"  # e.g., stable_gpg_key_private.asc
# --------------------------------

def sh(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, **kw)

def run(cmd, *, input_bytes=None, cwd=None, env=None):
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.run(
        cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        input=input_bytes, cwd=cwd, env=env
    )

def which_or_die(name):
    if shutil.which(name) is None:
        print(f"error: required tool '{name}' not found in PATH", file=sys.stderr)
        sys.exit(1)

def dpkg_field(deb, field):
    out = subprocess.check_output(["dpkg-deb", "-f", str(deb), field], text=True)
    return out.strip()

def import_key_and_get_fpr(gnupg_home: pathlib.Path, privkey_path: pathlib.Path) -> str:
    env = os.environ.copy()
    env["GNUPGHOME"] = str(gnupg_home)
    run(["gpg", "--batch", "--yes", "--import", str(privkey_path)], env=env)
    out = run(["gpg", "--batch", "--with-colons", "--list-secret-keys"], env=env).stdout.decode()
    fprs = [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:")]
    if not fprs:
        print("error: no secret key fingerprint found after import", file=sys.stderr)
        sys.exit(1)
    return fprs[0]

def sign_repo(repo_root: pathlib.Path, suite: str):
    """Import suite key from ./gpg_keys, prompt for pass, sign Release -> InRelease & Release.gpg, export pubkey."""
    privkey_path = KEYS_DIR / PRIVKEY_TPL.format(suite=suite)
    if not privkey_path.exists():
        print(f"error: missing private key {privkey_path}", file=sys.stderr)
        sys.exit(1)

    gnupg_home = pathlib.Path(tempfile.mkdtemp(prefix=f"gnupg-sign-{suite}-"))
    try:
        os.chmod(gnupg_home, 0o700)
    except Exception:
        pass

    try:
        fpr = import_key_and_get_fpr(gnupg_home, privkey_path)
        pw = getpass.getpass(f"GPG passphrase for key {fpr} ({suite}): ")

        env = os.environ.copy()
        env["GNUPGHOME"] = str(gnupg_home)
        gpg_base = [
            "gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
            "--passphrase", pw, "-u", fpr
        ]

        cwd = os.fspath(repo_root)
        # Detached Release.gpg
        sh(gpg_base + ["-abs", "-o", "Release.gpg", "Release"], cwd=cwd, env=env)
        # Clearsigned InRelease
        sh(gpg_base + ["--clearsign", "-o", "InRelease", "Release"], cwd=cwd, env=env)

        # Export matching public key for clients to download
        pub = run(["gpg", "--armor", "--export", fpr], env=env).stdout
        (repo_root / "h0-archive.gpg").write_bytes(pub)
    finally:
        shutil.rmtree(gnupg_home, ignore_errors=True)

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("stable", "unstable"):
        print(f"Usage: {sys.argv[0]} stable|unstable", file=sys.stderr)
        sys.exit(1)
    suite = sys.argv[1]

    # tools
    which_or_die("dpkg-scanpackages")
    which_or_die("apt-ftparchive")
    which_or_die("gpg")

    # inputs
    if not PKG_DIR.exists():
        print(f"error: missing {PKG_DIR}", file=sys.stderr)
        sys.exit(1)

    # repo root (flat layout)
    repo_root = REPO_BASE / suite
    if repo_root.exists():
        shutil.rmtree(repo_root)
    pool_root = repo_root / "pool" / COMPONENT
    pool_root.mkdir(parents=True, exist_ok=True)   # <-- fixed

    # copy .deb files into pool/<first-letter>/<pkg>/
    archs = set()
    debs = list(PKG_DIR.glob("*.deb"))
    if not debs:
        print("error: no .deb files in package_target/", file=sys.stderr)
        sys.exit(1)

    for deb in debs:
        pkg  = dpkg_field(deb, "Package")
        arch = dpkg_field(deb, "Architecture")
        archs.add(arch)
        dst = pool_root / pkg[0] / pkg
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(deb, dst / deb.name)

    # Packages / Packages.gz at repo root (flat)
    packages_path = repo_root / "Packages"
    with packages_path.open("w") as out:
        sh(["dpkg-scanpackages", "-m", str(pool_root), "/dev/null"], stdout=out)
    sh(["gzip", "-9f", str(packages_path)])  # -> Packages.gz

    # Release (no Codename; works across Debian/Ubuntu)
    release_path = repo_root / "Release"
    with release_path.open("w") as out:
        sh(["apt-ftparchive", "release", "."], cwd=repo_root, stdout=out)

    # prepend metadata
    meta = [
        "Origin: h0 Project",
        "Label: h0 APT",
        f"Suite: {suite}",
        f"Components: {COMPONENT}",
        f"Architectures: {' '.join(sorted(archs))}",
        "Description: Minimal repo for h0",
        "",
    ]
    release_path.write_text("\n".join(meta) + release_path.read_text())

    # sign with the suite's key
    sign_repo(repo_root, suite)

    print(f"{suite.capitalize()} flat repo built and signed at {repo_root}")
    print(f'Client example:\n  deb [signed-by=/usr/share/keyrings/h0-archive.gpg] https://hero-to-zero.ch/{suite}/apt ./')

if __name__ == "__main__":
    main()
