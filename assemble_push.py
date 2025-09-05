#!/usr/bin/env python3
import argparse, os, pathlib, shutil, sys, time, subprocess

def copy_tree(src: pathlib.Path, dst: pathlib.Path):
    for p in src.rglob("*"):
        if p.is_file():
            t = dst / p.relative_to(src)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, t)

def sh(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, **kw)

def main():
    ap = argparse.ArgumentParser(description="Assemble deployable directory (website + apt/<suite>)")
    ap.add_argument("--suite", choices=["stable","unstable"], required=True)
    ap.add_argument("--website", default="website_target")
    ap.add_argument("--repo-dir", default="apt_repo")
    ap.add_argument("--out", default=None, help="Output folder (default: deploy_dir_<suite>)")
    ap.add_argument("--git-init", action="store_true", help="Initialize a local git repo in the output")
    args = ap.parse_args()

    website = pathlib.Path(args.website)
    apt_src = pathlib.Path(args.repo_dir) / args.suite
    if not website.exists():
        print(f"missing {website}", file=sys.stderr); sys.exit(1)
    if not apt_src.exists():
        print(f"missing {apt_src} (did you run build_repo.py for {args.suite}?)", file=sys.stderr); sys.exit(1)

    outdir = pathlib.Path(args.out or f"deploy_dir_{args.suite}")
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)

    # website at root
    copy_tree(website, outdir)
    # apt under /apt/
    shutil.copytree(apt_src, outdir / "apt")

    # simple manifest
    (outdir / ".deploy-manifest.txt").write_text(
        f"suite={args.suite}\ncreated={time.strftime('%Y-%m-%d %H:%M:%S %z')}\n"
    )

    if args.git_init:
        sh(["git", "init", "-b", "main"], cwd=outdir)
        # ensure all files committed
        sh(["git", "add", "-A"], cwd=outdir)
        sh(["git", "commit", "-m", f"assemble {args.suite} {time.strftime('%Y%m%d-%H%M%S')}"], cwd=outdir)

    print(f"Assembled {outdir.resolve()}")

if __name__ == "__main__":
    main()
