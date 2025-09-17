import re
import unicodedata

# =========================
# Core helpers and scanners
# =========================

def normalize_token(token: str) -> str:
    """Canonical form: NFKC + casefold (locale-independent)."""
    return unicodedata.normalize("NFKC", token).casefold()

def is_ascii_admin(token: str) -> bool:
    return token == "admin"

def is_ascii_root(token: str) -> bool:
    return token == "root"

def is_ascii_user(token: str) -> bool:
    return token == "user"

# For admin: true bypass characters (Turkic i-variants & combining dot)
ADMIN_BAD_CHARS = re.compile(r"[\u0130\u0131\u0307]")

# For root/user: normalization-compatibility ranges
COMPAT_BAD_RANGES = re.compile(r"[\uFF00-\uFFEF\u1D400-\u1D7FF\u2460-\u24FF]")

WORD_RE = re.compile(r"\w+", re.UNICODE)

def scan_for_admin(s: str):
    """Return list of (token, 'admin-variant', start_idx, end_idx)."""
    findings = []
    for m in WORD_RE.finditer(s):
        word = m.group(0)
        if normalize_token(word) == "admin" and not is_ascii_admin(word):
            if ADMIN_BAD_CHARS.search(word) or COMPAT_BAD_RANGES.search(word):
                findings.append((word, "admin-variant", m.start(), m.end()))
    return findings

def scan_for_root(s: str):
    """Return list of (token, 'root-variant', start_idx, end_idx)."""
    findings = []
    for m in WORD_RE.finditer(s):
        word = m.group(0)
        if normalize_token(word) == "root" and not is_ascii_root(word):
            if COMPAT_BAD_RANGES.search(word):
                findings.append((word, "root-variant", m.start(), m.end()))
    return findings

def scan_for_user(s: str):
    """Return list of (token, 'user-variant', start_idx, end_idx)."""
    findings = []
    for m in WORD_RE.finditer(s):
        word = m.group(0)
        if normalize_token(word) == "user" and not is_ascii_user(word):
            if COMPAT_BAD_RANGES.search(word):
                findings.append((word, "user-variant", m.start(), m.end()))
    return findings

# =========================
# Check wrappers (booleans)
# =========================

def has_admin_issues(s: str) -> bool:
    return bool(scan_for_admin(s))

def has_root_issues(s: str) -> bool:
    return bool(scan_for_root(s))

def has_user_issues(s: str) -> bool:
    return bool(scan_for_user(s))

def has_any_issues(s: str) -> bool:
    return has_admin_issues(s) or has_root_issues(s) or has_user_issues(s)

# =========================
# Sanitization helpers
# =========================

def _preserve_simple_case(original: str, canonical_ascii: str) -> str:
    """
    Preserve simple casing style of the original token:
    - all upper   -> UPPER
    - all lower   -> lower
    - title case  -> Title
    - otherwise   -> canonical lower
    """
    if original.isupper():
        return canonical_ascii.upper()
    if original.islower():
        return canonical_ascii.lower()
    if original.istitle():
        return canonical_ascii.title()
    # Mixed or weird casing: default to lower
    return canonical_ascii.lower()

def _sanitize_against_target(s: str, target: str, scan_fn):
    """
    Replace any token in s that normalizes to `target` but isn't ASCII `target`
    with an ASCII/case-preserved version of `target`. Returns (new_s, replacements).
    replacements is a list of dicts: {'original', 'replacement', 'start', 'end'}.
    """
    # Collect ranges to replace (avoid overlapping edits by doing right-to-left)
    findings = scan_fn(s)
    if not findings:
        return s, []

    replacements = []
    s_list = list(s)
    # Process from end to start to keep indices valid
    for word, _kind, start, end in sorted(findings, key=lambda x: x[2], reverse=True):
        replacement = _preserve_simple_case(word, target)
        # Apply replacement
        s_list[start:end] = list(replacement)
        replacements.append({
            "original": word,
            "replacement": replacement,
            "start": start,
            "end": end
        })

    return "".join(s_list), list(reversed(replacements))

# =========================
# Sanitizer wrappers
# =========================

def sanitize_admin_string(s: str):
    """Sanitize problematic 'admin' tokens to ASCII 'admin' (case-preserved)."""
    return _sanitize_against_target(s, "admin", scan_for_admin)

def sanitize_root_string(s: str):
    """Sanitize problematic 'root' tokens to ASCII 'root' (case-preserved)."""
    return _sanitize_against_target(s, "root", scan_for_root)

def sanitize_user_string(s: str):
    """Sanitize problematic 'user' tokens to ASCII 'user' (case-preserved)."""
    return _sanitize_against_target(s, "user", scan_for_user)

def sanitize_all_issues(s: str):
    """
    Sanitize all three: admin, root, user.
    Returns (new_s, all_replacements) where all_replacements is a flat list.
    """
    out, rep_a = sanitize_admin_string(s)
    out, rep_r = sanitize_root_string(out)
    out, rep_u = sanitize_user_string(out)
    return out, rep_a + rep_r + rep_u

# =========================
# Example
# =========================
if __name__ == "__main__":
    sample = (
        "We saw ADMİN, admın, and admi̇n; plus ｒｏｏｔ and 𝐮𝐬𝐞𝐫. "
        "Normal admin, root, user should remain unchanged. "
        "Title case Admİn should become Admin."
    )

    print("has_admin_issues:", has_admin_issues(sample))
    print("has_root_issues:", has_root_issues(sample))
    print("has_user_issues:", has_user_issues(sample))
    print("has_any_issues:", has_any_issues(sample))

    sanitized, changes = sanitize_all_issues(sample)
    print("\nSanitized:\n", sanitized)
    print("\nChanges:")
    for c in changes:
        print(c)
