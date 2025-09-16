from typing import List, Tuple, Optional, Dict, Any
import unicodedata
import regex as re  # pip install regex
import os

# ------------------------------ helpers ------------------------------------

def _combining(ch: str) -> int:
    return unicodedata.combining(ch)

def _is_ctrl(ch: str) -> bool:
    c = ord(ch)
    # Tabs are allowed; not treated as control chars
    return (c < 0x20 and c not in (0x09,)) or c == 0x7F

def _nfkc_once(s: str) -> str:
    return s if unicodedata.is_normalized("NFKC", s) else unicodedata.normalize("NFKC", s)

# ---------------------- confusables (Unicode skeleton) ---------------------

_CONFUSABLES_MAP: Optional[Dict[str, str]] = None

def _load_confusables_map() -> Dict[str, str]:
    """
    Load mappings from confusables-minified.txt located in the same directory
    as this script. Each line has the form:
        <src> ; <dst> ; <status>
    """
    global _CONFUSABLES_MAP
    if _CONFUSABLES_MAP is not None:
        return _CONFUSABLES_MAP

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "confusables-minified.txt")
    mapping: Dict[str, str] = {}

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 2:
                continue
            src_hex, dst_hex = parts[0], parts[1]
            src = "".join(chr(int(cp, 16)) for cp in src_hex.split())
            dst = "".join(chr(int(cp, 16)) for cp in dst_hex.split())
            mapping[src] = dst

    _CONFUSABLES_MAP = mapping
    return mapping

def _apply_confusables(s: str) -> str:
    """
    Apply Unicode confusables skeleton mapping (after NFKC).
    Longest-match-first up to 4 codepoints.
    """
    mapping = _load_confusables_map()
    out = []
    i = 0
    while i < len(s):
        matched = False
        for j in range(min(4, len(s) - i), 0, -1):
            sub = s[i:i+j]
            if sub in mapping:
                out.append(mapping[sub])
                i += j
                matched = True
                break
        if not matched:
            out.append(s[i])
            i += 1
    return "".join(out)

# ======================= deceptive lines (check/sanitize) ===================

def deceptive_line_check(s: str, low_aggression: bool = True) -> List[Tuple[int, str]]:
    """
    Check a single line for deceptive Unicode. Intended for lines with no EOL/CR.
    - Scans ONLY up to first LF/CR (like sanitizer truncation).
    - Uses grapheme clusters (\\X) so legitimate ZWJ/ZWNJ/combining/emoji aren't mis-flagged.
    - Reports "Confusables/normalization" ONLY if low_aggression is False AND a change would occur.
    Returns [(codepoint_index, message)].
    """
    issues: List[Tuple[int, str]] = []

    # Determine scan limit (and report the break if present)
    stop = len(s)
    lf = s.find("\n"); cr = s.find("\r")
    if lf != -1 and (cr == -1 or lf < cr):
        stop = lf; issues.append((lf, "ASCII control: LINE FEED (U+000A)"))
    elif cr != -1:
        stop = cr; issues.append((cr, "ASCII control: CARRIAGE RETURN (U+000D)"))

    slice_ = s[:stop]

    bidi_controls = {"\u202A","\u202B","\u202D","\u202E","\u202C","\u2066","\u2067","\u2068","\u2069"}
    invisibles = {
        "\u200B":"Zero Width Space",
        "\u2060":"Word Joiner",
        "\uFEFF":"Zero Width No-Break Space (BOM)",
    }
    special_spaces = {
        "\u00A0":"No-Break Space","\u2002":"En Space","\u2003":"Em Space","\u2004":"Three-Per-Em Space",
        "\u2005":"Four-Per-Em Space","\u2006":"Six-Per-Em Space","\u2007":"Figure Space","\u2008":"Punctuation Space",
        "\u2009":"Thin Space","\u200A":"Hair Space","\u202F":"Narrow No-Break Space","\u205F":"Medium Mathematical Space",
        "\u3000":"Ideographic Space","\u2028":"Line Separator","\u2029":"Paragraph Separator",
    }

    cp_index = 0
    for m in re.finditer(r"\X", slice_):
        cluster = m.group(0)

        # ASCII controls (defensive; LF/CR already handled)
        for off, ch in enumerate(cluster):
            if _is_ctrl(ch):
                issues.append((cp_index + off, f"ASCII control: {unicodedata.name(ch, f'U+{ord(ch):04X}')}"))

        # BiDi controls
        for off, ch in enumerate(cluster):
            if ch in bidi_controls:
                issues.append((cp_index + off, "Bidi control character present"))

        # ZWJ/ZWNJ: solitary cluster is suspicious; otherwise OK
        if cluster == "\u200D":
            issues.append((cp_index, "Zero Width Joiner without surrounding grapheme"))
        if cluster == "\u200C":
            issues.append((cp_index, "Zero Width Non-Joiner without surrounding grapheme"))

        # Other invisibles & special spaces
        for off, ch in enumerate(cluster):
            if ch in invisibles:
                issues.append((cp_index + off, invisibles[ch]))
            label = special_spaces.get(ch)
            if label:
                issues.append((cp_index + off, f"Special space/separator: {label}"))

        # Dangling combining mark (cluster begins with combining)
        if _combining(cluster[0]) != 0:
            issues.append((cp_index, f"Combining mark not attached to base: {unicodedata.name(cluster[0], f'U+{ord(cluster[0]):04X}')}"))

        # Solitary variation selector
        if len(cluster) == 1 and 0xFE00 <= ord(cluster) <= 0xFE0F:
            issues.append((cp_index, "Variation Selector without base character"))

        cp_index += len(cluster)

    # Confusables/normalization (report only if sanitize would do it)
    if not low_aggression:
        mapped = _apply_confusables(_nfkc_once(slice_))
        if mapped != slice_:
            issues.append((0, "Confusables/normalization: would be normalized (NFKC + confusables skeleton)"))

    return issues


def deceptive_line_sanitize(
    s: str,
    low_aggression: bool = True,
    prefer_silent_removal: bool = False,
) -> Optional[str]:
    """
    Sanitize a single line (grapheme-aware).
    - If LF/CR present: truncate at first and append EOL/CR (or drop marker if prefer_silent_removal).
    - Replace/annotate BiDi controls, solitary ZWJ/ZWNJ, invisibles, special spaces,
      dangling combining marks, solitary VS. Keep legitimate grapheme clusters intact.
    - If low_aggression is False, apply NFKC + confusables skeleton mapping (silent).
    - If prefer_silent_removal is True, remove problematic codepoints instead of inserting tokens,
      but prefer sensible single-char substitutes (e.g., special spaces → ' ').
    Returns None if no changes; else the new string.
    """
    # Truncate at EOL/CR
    lf = s.find("\n"); cr = s.find("\r")
    if lf != -1 and (cr == -1 or lf < cr):
        return s[:lf] if prefer_silent_removal else (s[:lf] + "EOL")
    if cr != -1:
        return s[:cr] if prefer_silent_removal else (s[:cr] + "CR")

    changed = False
    out_parts: List[str] = []

    bidi_controls = {"\u202A","\u202B","\u202D","\u202E","\u202C","\u2066","\u2067","\u2068","\u2069"}
    inv_tok = { "\u200B":"ZWSP", "\u2060":"WJ", "\uFEFF":"BOM" }
    space_tok = {
        "\u00A0":"NBSP","\u2002":"ENSP","\u2003":"EMSP","\u2004":"THREESP","\u2005":"FOURSP","\u2006":"SIXSP",
        "\u2007":"FIGSP","\u2008":"PUNCSP","\u2009":"THIN","\u200A":"HAIR","\u202F":"NNBSP","\u205F":"MMSP",
        "\u3000":"IDEOSPC","\u2028":"LS","\u2029":"PS",
    }

    for m in re.finditer(r"\X", s):
        cluster = m.group(0)

        # Replace/Remove ASCII controls in cluster
        if any(_is_ctrl(ch) for ch in cluster):
            if prefer_silent_removal:
                new = "".join(ch for ch in cluster if not _is_ctrl(ch))
            else:
                new = "".join("CTRL" if _is_ctrl(ch) else ch for ch in cluster)
            if new != cluster:
                changed = True; out_parts.append(new); continue

        # Replace/Remove BiDi controls in cluster
        if any(ch in bidi_controls for ch in cluster):
            if prefer_silent_removal:
                new = "".join(ch for ch in cluster if ch not in bidi_controls)
            else:
                new = "".join("BIDI" if ch in bidi_controls else ch for ch in cluster)
            changed = True; out_parts.append(new); continue

        # Solitary joiners
        if cluster == "\u200D":
            out_parts.append("" if prefer_silent_removal else "ZWJ"); changed = True; continue
        if cluster == "\u200C":
            out_parts.append("" if prefer_silent_removal else "ZWNJ"); changed = True; continue

        # Invisibles & special spaces (per codepoint)
        rep = False; tmp = []
        for ch in cluster:
            if ch in inv_tok:
                if prefer_silent_removal:
                    rep = True  # drop it
                    # don't append anything
                else:
                    tmp.append(inv_tok[ch]); rep = True
            else:
                if ch in space_tok:
                    # single-char sensible substitute: replace with regular space
                    tmp.append(" "); rep = True; changed = True
                else:
                    tmp.append(ch)
        if rep:
            changed = True; out_parts.append("".join(tmp)); continue

        # Dangling combining mark
        if _combining(cluster[0]) != 0:
            if prefer_silent_removal:
                out_parts.append(cluster[1:])  # drop unattached combining mark
            else:
                out_parts.append("CM" + cluster[1:])
            changed = True; continue

        # Solitary VS
        if len(cluster) == 1 and 0xFE00 <= ord(cluster) <= 0xFE0F:
            out_parts.append("" if prefer_silent_removal else "VS"); changed = True; continue

        out_parts.append(cluster)

    result = "".join(out_parts)

    # Homoglyph normalization (aggressive only)
    if not low_aggression:
        post = _apply_confusables(_nfkc_once(result))
        if post != result:
            return post

    return None if not changed else result

# =============================== filenames =================================

# Tokens for filename sanitization/truncation
FNAME_MARK = {
    "SLASH":"SLASH","DOTSLASH":"DOTSLASH","DOTDOTSLASH":"DOTDOTSLASH","WS":"WS","EOL":"EOL","CR":"CR"
}

# Treat all hazards equally
ASCII_HAZARDS_ANYWHERE: Dict[str, str] = {
    "*": "Dangerous char: '*' glob expansion",
    "?": "Dangerous char: '?' single-char glob",
    "[": "Dangerous char: '[' starts a glob class",
    "]": "Dangerous char: ']' ends a glob class",
    "'": "Dangerous char: single quote breaks quoting",
    '"': "Dangerous char: double quote breaks quoting",
    "`": "Dangerous char: backtick command substitution",
    "\\": "Dangerous char: backslash escape",
    "<": "Dangerous char: input redirection",
    ">": "Dangerous char: output redirection",
    "|": "Dangerous char: pipe operator",
    "&": "Dangerous char: background/separator",
    ";": "Dangerous char: command separator",
    "!": "Dangerous char: history expansion in some shells",
    "#": "Dangerous char: comment leader in scripts",
    ":": "Dangerous char: colon may be path/URL separator",
    "~": "Dangerous char: home expansion",
    "$": "Dangerous char: variable expansion",
    "%": "Dangerous char: formatting/printf contexts",
    ",": "Dangerous char: CSV/arg parsing contexts",
    "@": "Dangerous char: host/user separators",
    "/": "Illegal in POSIX filenames: path separator",
}

# Single replacement table used for ALL hazards above
TOKENS: Dict[str, str] = {
    "*":"STAR","?":"QMARK","[":"LBRACK","]":"RBRACK",
    "'":"SQUOTE",'"':"DQUOTE","`":"BQUOTE","\\":"BSLASH",
    "<":"LT",">":"GT","|":"PIPE","&":"AMP",";":"SEMI","!":"EXCL","#":"HASH",
    ":":"COLON","~":"TILDE","$":"DOLLAR","%":"PERCENT",",":"COMMA","@":"AT",
    "/":"SLASH",
}

# Start-of-name rules
StartRule = Dict[str, Any]
START_RULES: List[StartRule] = [
    {
        "name": "exact-dotdot",
        "match_len": lambda s: 2 if s == ".." else 0,
        "check_msg": "Exact '..': refers to parent directory",
        # sanitize handled in _apply_start_rules_for_sanitize based on prefer_silent_removal
    },
    {
        "name": "prefix-dotdotslash",
        "match_len": lambda s: 3 if s.startswith("../") else 0,
        "check_msg": "Starts with '../': parent-relative path",
    },
    {
        "name": "prefix-dotslash",
        "match_len": lambda s: 2 if s.startswith("./") else 0,
        "check_msg": "Starts with './': relative path prefix",
    },
    {
        "name": "prefix-slash",
        "match_len": lambda s: 1 if s.startswith("/") else 0,
        "check_msg": "Starts with '/': absolute path, not a bare filename",
    },
]

def _apply_start_rules_for_check(name: str) -> List[Tuple[int, str]]:
    issues: List[Tuple[int, str]] = []
    for rule in START_RULES:
        m = rule["match_len"](name)
        if m:
            issues.append((0, rule["check_msg"]))
    return issues

def _apply_start_rules_for_sanitize(name: str, prefer_silent_removal: bool) -> Optional[str]:
    """
    Apply start rules:
      - If prefer_silent_removal is True, *remove* the dangerous prefix (e.g., '../', './', '/'),
        or drop '..' entirely.
      - Otherwise, replace with explicit markers (DOTDOTSLASH, DOTSLASH, SLASH, DOTDOT).
    """
    out = name
    changed = False

    # exact '..'
    if out == "..":
        out = "" if prefer_silent_removal else "DOTDOT"
        changed = True
        return out

    # '../'
    if out.startswith("../"):
        out = out[3:] if prefer_silent_removal else (FNAME_MARK["DOTDOTSLASH"] + out[3:])
        changed = True

    # './'
    if out.startswith("./"):
        out = out[2:] if prefer_silent_removal else (FNAME_MARK["DOTSLASH"] + out[2:])
        changed = True

    # leading '/'
    if out.startswith("/"):
        out = out[1:] if prefer_silent_removal else (FNAME_MARK["SLASH"] + out[1:])
        changed = True

    return out if changed else None

# ------------------------------- checker -----------------------------------

def bad_filename_check(name: str) -> List[Tuple[int, str]]:
    """
    Check filename start patterns, embedded LF/CR (stop at first one),
    and dangerous printable ASCII ANYWHERE (including '/').
    NOTE (2025): Plain ASCII spaces are allowed and NOT flagged.
    NOTE: Empty string is considered valid here (no issues).
    """
    issues: List[Tuple[int, str]] = []
    if name == "":
        return issues  # empty is considered valid (no messages)

    stop = len(name)
    lf = name.find("\n"); cr = name.find("\r")
    if lf != -1 and (cr == -1 or lf < cr):
        stop = lf; issues.append((lf, "Contains LF (U+000A): end-of-line in many tools"))
    elif cr != -1:
        stop = cr; issues.append((cr, "Contains CR (U+000D): carriage return; may corrupt display/processing"))

    # Start rules (DRY)
    issues.extend(_apply_start_rules_for_check(name[:stop]))

    # Anywhere ASCII hazards (spaces deliberately ignored)
    for i, ch in enumerate(name[:stop]):
        msg = ASCII_HAZARDS_ANYWHERE.get(ch)
        if msg:
            issues.append((i, msg))

    return issues

# ------------------------------ sanitizer ----------------------------------

def bad_filename_sanitize(
    name: str,
    prefer_silent_removal: bool = False,
) -> Optional[str]:
    """
    Sanitize filename using start rules, LF/CR truncation, and ASCII replacements.
    - At LF/CR: truncate at first and append EOL/CR token, or drop marker if prefer_silent_removal.
    - Apply start rules (lone '.' untouched).
    - Replace ALL dangerous ASCII anywhere (space is allowed):
        * If prefer_silent_removal is False -> replace using TOKENS (e.g., '/' -> 'SLASH').
        * If prefer_silent_removal is True  -> remove the hazardous character entirely.
      (There is no good single-char substitute for these in filenames.)
    - If name is empty, DO NOT sanitize (return None).
    Returns None if no changes; otherwise the new name (may be empty string if everything was removed).
    """
    if name == "":
        return None  # empty is allowed; no auto-sanitize

    lf = name.find("\n"); cr = name.find("\r")
    if lf != -1 and (cr == -1 or lf < cr):
        return name[:lf] if prefer_silent_removal else (name[:lf] + FNAME_MARK["EOL"])
    if cr != -1:
        return name[:cr] if prefer_silent_removal else (name[:cr] + FNAME_MARK["CR"])

    changed = False
    out = name

    repl = _apply_start_rules_for_sanitize(out, prefer_silent_removal)
    if repl is not None:
        out = repl; changed = True

    parts: List[str] = []
    for ch in out:
        if ch in TOKENS:
            if prefer_silent_removal:
                # drop the hazardous char
                changed = True
                continue
            else:
                parts.append(TOKENS[ch]); changed = True
        else:
            parts.append(ch)

    out2 = "".join(parts)
    return None if not changed else out2
