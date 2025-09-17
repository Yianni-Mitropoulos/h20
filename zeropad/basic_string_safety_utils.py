from pathlib import Path
import regex

# Suspicious Unicode whitespace characters that look like or mimic ASCII space
SUSPICIOUS_SPACES = {
    "\u00A0",  # NO-BREAK SPACE
    "\u1680",  # OGHAM SPACE MARK
    "\u2000",  # EN QUAD
    "\u2001",  # EM QUAD
    "\u2002",  # EN SPACE
    "\u2003",  # EM SPACE
    "\u2004",  # THREE-PER-EM SPACE
    "\u2005",  # FOUR-PER-EM SPACE
    "\u2006",  # SIX-PER-EM SPACE
    "\u2007",  # FIGURE SPACE
    "\u2008",  # PUNCTUATION SPACE
    "\u2009",  # THIN SPACE
    "\u200A",  # HAIR SPACE
    "\u202F",  # NARROW NO-BREAK SPACE
    "\u205F",  # MEDIUM MATHEMATICAL SPACE
    "\u3000",  # IDEOGRAPHIC SPACE
    "\u180E",  # MONGOLIAN VOWEL SEPARATOR (deprecated; occasionally space-like in old renderers)
}

# ---------------------
# Grapheme segmentation
# ---------------------

_GRAPHEME_RE = regex.compile(r"\X")
def graphemes(s: str):
    return _GRAPHEME_RE.findall(s)

# ----------------------------------------------
# Confusables (minified) loader and skeletonizer
# ----------------------------------------------

_CONFUSABLE_MAP = None  # cache

def _default_confusables_path() -> Path:
    """File expected to live next to this module."""
    return Path(__file__).with_name("confusables-minified.txt")

def load_confusables(path: str | Path | None = None) -> dict[str, str]:
    """
    Load a char→string mapping from a minified confusables file.
    Expected line format (comments allowed, ignored after '#'):
        <SRC_HEX> ; <DST_HEX_SEQ> ; <TYPE>
    """
    global _CONFUSABLE_MAP
    if path is None and _CONFUSABLE_MAP is not None:
        return _CONFUSABLE_MAP

    mapping: dict[str, str] = {}
    p = Path(path) if path is not None else _default_confusables_path()

    with p.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = [seg.strip() for seg in line.split(";")]
            if len(parts) < 2:
                continue
            src_hex = parts[0].split()[0]          # first token = single code point
            dst_hex_seq = parts[1].split()         # one or more code points

            try:
                src_char = chr(int(src_hex, 16))
            except ValueError:
                continue

            dst = "".join(chr(int(h, 16)) for h in dst_hex_seq if h)
            mapping[src_char] = dst

    if path is None:
        _CONFUSABLE_MAP = mapping
    return mapping

def confusable_skeleton(text: str, mapping: dict[str, str] | None = None) -> str:
    """Return the ASCII-ish skeleton by applying the confusables map char-by-char."""
    if mapping is None:
        mapping = load_confusables(None)
    return "".join(mapping.get(ch, ch) for ch in text)

# -------------------------------------
# Core visibility/ASCII-pretender logic
# -------------------------------------

def apparent_width(g, font) -> int:
    """Return apparent width (pixels) of grapheme g with given Tk font."""
    try:
        return font.measure(g)
    except Exception:
        return 0

def looks_like_ascii(g: str, font) -> bool:
    """
    Return True if grapheme g *renders like* ASCII, approximated by:
    - the grapheme being some kind of nonstandard space character, or
    - the confusable_skeleton(g) consisting only of ASCII code points (0..127).
    """
    if g in SUSPICIOUS_SPACES:
        return True
    skeleton = confusable_skeleton(g)
    return bool(skeleton and all(ord(c) < 128 for c in skeleton))

def clearly_unicode(g: str, font) -> bool:
    """Return True if grapheme g is visibly non-ASCII in this font."""
    if apparent_width(g, font) == 0:
        return False
    if looks_like_ascii(g, font):
        return False
    return True

def ascii_pretender(line: str, font) -> bool:
    """
    Return True if the line looks like pure ASCII but isn't.
    Uses grapheme clustering + font width + confusables skeletonization.
    """
    # 1. Pure ASCII → not suspicious
    if all(ord(c) < 128 for c in line):
        return False

    # 2. Any clearly visible non-ASCII grapheme? → not suspicious
    if any(clearly_unicode(g, font) for g in graphemes(line)):
        return False

    # 3. Otherwise → suspicious
    return True

# ----------------------------------------------
# Extra helpers (for general text and filenames)
# ----------------------------------------------

def contains_ascii_control_chars(line: str, strict: bool = False) -> bool:
    """
    Detect ASCII control characters.
    If strict=True, even \\n, \\r, \\t are considered problematic.
    """
    for c in line:
        code = ord(c)
        if code < 32 or code == 127:
            if not strict and c in ("\n", "\r", "\t"):
                continue
            return True
    return False

def exists_outside_printable_ascii_plane(line: str) -> bool:
    """
    Return True if the line contains anything outside the printable ASCII plane.
    - Flags ASCII control characters (but treats \n, \r, \t as OK).
    - Flags any non-ASCII code point (>= 128).
    """
    if contains_ascii_control_chars(line, strict=False):
        return True
    if any(ord(c) >= 128 for c in line):
        return True
    return False

def suspicious_line(line: str, font, strict: bool = False) -> bool:
    """
    A general-purpose suspiciousness check for text lines.
    Combines ASCII control char detection with ASCII pretender detection.
    """
    if contains_ascii_control_chars(line, strict=strict):
        return True
    if ascii_pretender(line, font):
        return True
    return False

def deceptive_whitespace_check(line: str) -> bool:
    """
    Flag deceptive whitespace:
      - Leading whitespace
      - Trailing whitespace
      - Adjacent space characters (double spaces)
    """
    if line.startswith(" "):
        return True
    if line.endswith(" "):
        return True
    if "  " in line:  # double space
        return True
    return False

def contains_dquote_badchars(line: str) -> bool:
    """
    Flag characters that are especially problematic inside double quotes
    across many languages (bash, Python, C, JS).
    """
    badchars = {'$', '`', '"', '\\', '{', '}', '%', '!'}
    return any(c in badchars for c in line)

def suspicious_filename(line: str, font) -> bool:
    """
    Special-purpose suspiciousness check for filenames.
    Combines:
      - suspicious_line(strict=True)
      - contains_dquote_badchars()
      - deceptive_whitespace_check()
    """
    if suspicious_line(line, font, strict=True):
        return True
    if contains_dquote_badchars(line):
        return True
    if deceptive_whitespace_check(line):
        return True
    return False

def suspicious_filename_strict(line: str) -> bool:
    """
    Strict filename check: True if the filename contains any character
    outside the exact detox safe set: [A-Za-z0-9._+-]
    """
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-")
    return any(c not in safe_chars for c in line)
