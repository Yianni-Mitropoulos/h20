#!/usr/bin/env python3
# build_signed_website.py
#
# - Reads HTML from ./website_target
# - Replaces placeholders {suite} and {gpg_key_public}
# - Adds SRI (sha384) to local <script src> and <link rel="stylesheet" href> assets
# - Signs the canonicalized <html>...</html> bytes with GPG (detached, ASCII-armored)
# - Injects the signature as the FIRST HTML comment (or right after <!DOCTYPE ...>)
# - Writes the result to ./signed_website_target
#
# Keys are loaded from: ./gpg_keys/{suite}_gpg_key_public.asc and ./gpg_keys/{suite}_gpg_key_private.asc

import argparse
import base64
import getpass
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

# ---------- Config ----------
WEBSITE_SRC_DIRNAME = "website_target"
SIGNED_DST_DIRNAME = "signed_website_target"
KEYS_DIRNAME = "gpg_keys"

PUBKEY_TEMPLATE = "{gpg_key_public}"
SUITE_TEMPLATE = "{suite}"

PUBKEY_FILENAME = "{suite}_gpg_key_public.asc"
PRIVKEY_FILENAME = "{suite}_gpg_key_private.asc"

SRI_ALGO = "sha384"
# ----------------------------


def run(cmd, *, input_bytes=None, cwd=None, env=None):
    print("+", " ".join(cmd))
    return subprocess.run(
        cmd,
        input=input_bytes,
        cwd=cwd,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def write_text(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def sri_digest_for_file(path: Path, algo: str = SRI_ALGO) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return algo + "-" + base64.b64encode(h.digest()).decode("ascii")


def is_url_external(url: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.+-]*://", url or ""))


def is_probably_html_url(url: str) -> bool:
    return (url or "").lower().endswith((".html", ".htm"))


class SRIInjectingParser(HTMLParser):
    """
    Preserve original markup as much as possible:
      - Use get_starttag_text() to append start tags verbatim.
      - Patch start tags in-place only when needed (placeholder substitution and/or SRI).
      - Emit end tags only if they appeared in the source (HTMLParser calls handle_endtag then).
      - Replace placeholders in text and comments.
    """

    def __init__(self, base_dir: Path, replacements: dict):
        super().__init__(convert_charrefs=True)
        self.base_dir = base_dir
        self.repl = replacements
        self.out = []

    # ---- helpers ------------------------------------------------------------

    def _repl_text(self, s: str) -> str:
        if not s:
            return s
        s = s.replace(SUITE_TEMPLATE, self.repl[SUITE_TEMPLATE])
        s = s.replace(PUBKEY_TEMPLATE, self.repl[PUBKEY_TEMPLATE])
        return s

    def _patch_starttag(self, original: str, add_attrs: dict) -> str:
        """
        Insert attributes (e.g., integrity, crossorigin) into the original start tag text
        with minimal changes. Also perform placeholder replacement.
        """
        if not original:
            return original

        tag_txt = self._repl_text(original)

        if not add_attrs:
            return tag_txt

        # Avoid duplicates
        has_integrity = re.search(r"\bintegrity\s*=", tag_txt, flags=re.I)
        has_crossorigin = re.search(r"\bcrossorigin\s*=", tag_txt, flags=re.I)

        parts_to_add = []
        if "integrity" in add_attrs and not has_integrity:
            parts_to_add.append(' integrity="' + add_attrs["integrity"] + '"')
        if "crossorigin" in add_attrs and not has_crossorigin:
            parts_to_add.append(' crossorigin="' + add_attrs["crossorigin"] + '"')

        if not parts_to_add:
            return tag_txt

        # Insert right before final '>' or '/>'
        m = re.search(r"\s*/?\s*>$", tag_txt)
        if not m:
            return tag_txt + "".join(parts_to_add) + ">"
        insert_at = m.start()
        return tag_txt[:insert_at] + "".join(parts_to_add) + tag_txt[insert_at:]

    # ---- HTMLParser callbacks ----------------------------------------------

    def handle_decl(self, decl):
        self.out.append("<!" + decl + ">")

    def handle_starttag(self, tag, attrs):
        add = {}
        attrs_dict = dict(attrs)

        # Decide whether we need SRI on local non-HTML assets
        if tag.lower() == "script" and "src" in attrs_dict:
            src = self._repl_text(attrs_dict["src"])
            if src and not is_url_external(src) and not is_probably_html_url(src):
                asset = (self.base_dir / src).resolve()
                if asset.exists():
                    add["integrity"] = sri_digest_for_file(asset)
                    add.setdefault("crossorigin", "anonymous")

        if tag.lower() == "link" and "href" in attrs_dict:
            rel = (attrs_dict.get("rel") or "").lower()
            href = self._repl_text(attrs_dict["href"])
            if "stylesheet" in rel and href and not is_url_external(href) and not is_probably_html_url(href):
                asset = (self.base_dir / href).resolve()
                if asset.exists():
                    add["integrity"] = sri_digest_for_file(asset)
                    add.setdefault("crossorigin", "anonymous")

        self.out.append(self._patch_starttag(self.get_starttag_text(), add))

    def handle_startendtag(self, tag, attrs):
        # Same treatment as starttag; get_starttag_text preserves '/>' vs '>'
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        # HTMLParser only calls this if the source had an explicit end tag
        self.out.append("</" + tag + ">")

    def handle_data(self, data):
        self.out.append(self._repl_text(data))

    def handle_comment(self, data):
        self.out.append("<!--" + self._repl_text(data) + "-->")

    def handle_entityref(self, name):
        self.out.append("&" + name + ";")

    def handle_charref(self, name):
        self.out.append("&#" + name + ";")

    def get_html(self) -> str:
        return "".join(self.out)


def minify_html_body(html_text: str) -> str:
    """
    Canonicalize the region we sign: exactly the <html>...</html> if present.
    Remove comments and collapse inter-tag whitespace to stabilize bytes.
    """
    m = re.search(r"<html\b[^>]*>(.*?)</html\s*>", html_text, flags=re.IGNORECASE | re.DOTALL)
    body = m.group(0) if m else html_text
    # remove all HTML comments
    body = re.sub(r"(?s)<!--.*?-->", "", body)
    # collapse whitespace between tags
    body = re.sub(r">\s+<", "><", body)
    return body.strip()


def import_key_and_get_fpr(gnupg_home: Path, privkey_path: Path) -> str:
    env = os.environ.copy()
    env["GNUPGHOME"] = str(gnupg_home)
    run(["gpg", "--batch", "--yes", "--import", str(privkey_path)], env=env)
    out = run(["gpg", "--batch", "--with-colons", "--list-secret-keys"], env=env).stdout.decode()
    fprs = [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:")]
    if not fprs:
        sys.stderr.write("error: no secret key fingerprint found after import\n")
        sys.exit(1)
    return fprs[0]


def gpg_detached_sign_ascii(gnupg_home: Path, keyid: str, passphrase: str, payload: bytes) -> str:
    env = os.environ.copy()
    env["GNUPGHOME"] = str(gnupg_home)
    cp = run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            passphrase,
            "-u",
            keyid,
            "--armor",
            "--detach-sign",
        ],
        input_bytes=payload,
        env=env,
    )
    return cp.stdout.decode("utf-8")


def insert_signature_comment(html_text: str, armored_sig: str) -> str:
    """
    Insert the ASCII-armored detached signature as the FIRST comment.
    If a doctype exists, place the comment immediately after it.
    """
    sig_comment = "<!--\n" + armored_sig.strip() + "\n-->\n"
    m = re.match(r"(<!DOCTYPE[^>]*>\s*)", html_text, flags=re.IGNORECASE)
    if m:
        return html_text[: m.end(1)] + sig_comment + html_text[m.end(1) :]
    return sig_comment + html_text


def main():
    ap = argparse.ArgumentParser(description="Build signed website with SRI and Signed Pages signatures.")
    ap.add_argument("suite", nargs="?", choices=["stable", "unstable"], default="unstable", help="suite to use")
    args = ap.parse_args()
    suite = args.suite

    cwd = Path.cwd()
    src_root = cwd / WEBSITE_SRC_DIRNAME
    dst_root = cwd / SIGNED_DST_DIRNAME
    keys_root = cwd / KEYS_DIRNAME

    if not src_root.exists():
        sys.stderr.write("error: expected " + str(src_root) + " to exist\n")
        sys.exit(1)

    pubkey_path = keys_root / PUBKEY_FILENAME.format(suite=suite)
    privkey_path = keys_root / PRIVKEY_FILENAME.format(suite=suite)
    if not pubkey_path.exists() or not privkey_path.exists():
        sys.stderr.write("error: missing gpg key files in " + str(keys_root) + "\n")
        sys.exit(1)

    pubkey_armored = read_text(pubkey_path).strip()

    # Prepare isolated keyring and import secret key
    gnupg_home = Path(tempfile.mkdtemp(prefix="gnupg-home-"))
    try:
        os.chmod(gnupg_home, 0o700)
    except Exception:
        pass
    keyid_fpr = import_key_and_get_fpr(gnupg_home, privkey_path)
    passphrase = getpass.getpass("GPG passphrase for key " + keyid_fpr + ": ")

    # Prepare destination
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)

    replacements = {SUITE_TEMPLATE: suite, PUBKEY_TEMPLATE: pubkey_armored}

    # Walk and process
    for src_path in src_root.rglob("*"):
        rel = src_path.relative_to(src_root)
        dst_path = dst_root / rel

        if src_path.is_dir():
            dst_path.mkdir(parents=True, exist_ok=True)
            continue

        # Only process HTML/HTM through the parser/signing pipeline
        if src_path.suffix.lower() in (".html", ".htm"):
            parser = SRIInjectingParser(src_root, replacements)
            parser.feed(read_text(src_path))
            transformed = parser.get_html()

            # Canonical payload and sign
            canonical = minify_html_body(transformed).encode("utf-8")
            armored_sig = gpg_detached_sign_ascii(gnupg_home, keyid_fpr, passphrase, canonical)

            # Insert signature comment at top (or right after doctype)
            final_html = insert_signature_comment(transformed, armored_sig)
            write_text(dst_path, final_html)
        else:
            # Non-HTML: copy as-is
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)

    shutil.rmtree(gnupg_home, ignore_errors=True)
    print("\nSigned site built at:", dst_root)
    print("Replacements: {suite}, {gpg_key_public}; SRI added to local JS/CSS; HTML signed with detached ASCII-armored sig.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.stderr.write("\ncommand failed:\n")
        sys.stderr.write(e.stderr.decode("utf-8", errors="ignore"))
        sys.exit(e.returncode)
