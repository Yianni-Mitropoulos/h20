from typing import List, Tuple, Optional, Dict, Any
import unicodedata
import regex as re  # pip install regex

# ------------------------------ helpers ------------------------------------

def _combining(ch: str) -> int:
    return unicodedata.combining(ch)

def _is_ctrl(ch: str) -> bool:
    c = ord(ch)
    return c < 0x20 or c == 0x7F

def _nfkc_once(s: str) -> str:
    return s if unicodedata.is_normalized("NFKC", s) else unicodedata.normalize("NFKC", s)

# ------------------------ confusables (broad map) --------------------------

CONFUSABLES_XSCRIPT: Dict[str, str] = {
    # Cyrillic (upper)
    "А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","У":"Y","Х":"X",
    "І":"I","Ј":"J","Ѕ":"S","Ъ":"b","Ь":"b","Ґ":"G",
    # Cyrillic (lower)
    "а":"a","е":"e","о":"o","р":"p","с":"c","у":"y","х":"x","і":"i","ј":"j","ѕ":"s","ё":"e","ӏ":"l","Ӏ":"I",
    # Greek (upper)
    "Α":"A","Β":"B","Ε":"E","Ζ":"Z","Η":"H","Ι":"I","Κ":"K","Μ":"M","Ν":"N","Ο":"O","Ρ":"P","Τ":"T","Υ":"Y","Χ":"X",
    # Greek (lower) — conservative
    "ο":"o","ρ":"p","τ":"t","υ":"y","χ":"x","ι":"i","κ":"k","ν":"v","ε":"e","σ":"s",
    # Modifier/letterlikes/roman numerals
    "ˡ":"l","ᵢ":"i","ᵣ":"r","ᵤ":"u","ᵥ":"v","ᵇ":"b","ᵈ":"d","ᵍ":"g","ʰ":"h","ʲ":"j","ʳ":"r","ʷ":"w","ʸ":"y",
    "ʟ":"L","ɩ":"i","ɪ":"I","Ɩ":"I","ɫ":"l","ℓ":"l","ʋ":"v","ʏ":"Y","Ɔ":"C","ⅽ":"c","ⅰ":"i","ⅱ":"ii","ⅲ":"iii",
    "Ⅰ":"I","Ⅱ":"II","Ⅲ":"III","Ⅳ":"IV","Ⅴ":"V","Ⅵ":"VI","Ⅶ":"VII","Ⅷ":"VIII","Ⅸ":"IX","Ⅹ":"X",
}
def _apply_confusables(s: str) -> str:
    return "".join(CONFUSABLES_XSCRIPT.get(ch, ch) for ch in s)

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
            issues.append((0, "Confusables/normalization: would be normalized (NFKC + cross-script mapping)"))

    return issues


def deceptive_line_sanitize(s: str, low_aggression: bool = True) -> Optional[str]:
    """
    Sanitize a single line (grapheme-aware).
    - If LF/CR present: truncate at first and append EOL/CR.
    - Replace/annotate BiDi controls, solitary ZWJ/ZWNJ, invisibles, special spaces,
      dangling combining marks, solitary VS. Keep legitimate grapheme clusters intact.
    - If low_aggression is False, apply NFKC + cross-script confusables mapping (silent).
    Returns None if no changes; else the new string.
    """
    # Truncate at EOL/CR
    lf = s.find("\n"); cr = s.find("\r")
    if lf != -1 and (cr == -1 or lf < cr):
        return s[:lf] + "EOL"
    if cr != -1:
        return s[:cr] + "CR"

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

        # Replace ASCII controls
        if any(_is_ctrl(ch) for ch in cluster):
            new = "".join("CTRL" if _is_ctrl(ch) else ch for ch in cluster)
            if new != cluster:
                changed = True; out_parts.append(new); continue

        # Replace BiDi controls
        if any(ch in bidi_controls for ch in cluster):
            new = "".join("BIDI" if ch in bidi_controls else ch for ch in cluster)
            changed = True; out_parts.append(new); continue

        # Solitary joiners
        if cluster == "\u200D":
            out_parts.append("ZWJ"); changed = True; continue
        if cluster == "\u200C":
            out_parts.append("ZWNJ"); changed = True; continue

        # Invisibles & special spaces (per codepoint)
        rep = False; tmp = []
        for ch in cluster:
            if ch in inv_tok:
                tmp.append(inv_tok[ch]); rep = True
            else:
                token = space_tok.get(ch)
                if token:
                    tmp.append(token); rep = True
                else:
                    tmp.append(ch)
        if rep:
            changed = True; out_parts.append("".join(tmp)); continue

        # Dangling combining mark
        if _combining(cluster[0]) != 0:
            out_parts.append("CM" + cluster[1:]); changed = True; continue

        # Solitary VS
        if len(cluster) == 1 and 0xFE00 <= ord(cluster) <= 0xFE0F:
            out_parts.append("VS"); changed = True; continue

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

# Checker messages for dangerous ASCII anywhere (always + contextual)
# NOTE (2025): Raw ASCII spaces are accepted and NOT flagged.
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
    ":": "Dangerous contextual char: remote/path separator in scp/rsync/URLs",
    "~": "Dangerous contextual char: home expansion",
    "$": "Dangerous contextual char: variable expansion",
    "%": "Dangerous contextual char: printf/format contexts",
    ",": "Dangerous contextual char: CSV/arg parsing contexts",
    "@": "Dangerous contextual char: host/user separators in tools",
    "/": "Illegal in POSIX filenames: path separator",
}

# Replacements (sanitizer). NOTE: no mapping for space anymore.
TOKENS_ALWAYS = {
    "*":"STAR","?":"QMARK","[":"LBRACK","]":"RBRACK",
    "'":"SQUOTE",'"':"DQUOTE","`":"BQUOTE","\\":"BSLASH",
    "<":"LT",">":"GT","|":"PIPE","&":"AMP",";":"SEMI","!":"EXCL","#":"HASH",
    "/":"SLASH",
}
TOKENS_CONTEXTUAL = { ":":"COLON","~":"TILDE","$":"DOLLAR","%":"PERCENT",",":"COMMA","@":"AT" }

# Start-of-name rules (lone leading '.' preserved; no leading whitespace rule)
StartRule = Dict[str, Any]
START_RULES: List[StartRule] = [
    {
        "name": "exact-dotdot",
        "match_len": lambda s: 2 if s == ".." else 0,
        "check_msg": "Exact '..': refers to parent directory",
        "sanitize": lambda s, m: "DOTDOT",
    },
    {
        "name": "prefix-dotdotslash",
        "match_len": lambda s: 3 if s.startswith("../") else 0,
        "check_msg": "Starts with '../': parent-relative path",
        "sanitize": lambda s, m: FNAME_MARK["DOTDOTSLASH"] + s[m:],
    },
    {
        "name": "prefix-dotslash",
        "match_len": lambda s: 2 if s.startswith("./") else 0,
        "check_msg": "Starts with './': relative path prefix",
        "sanitize": lambda s, m: FNAME_MARK["DOTSLASH"] + s[m:],
    },
    {
        "name": "prefix-slash",
        "match_len": lambda s: 1 if s.startswith("/") else 0,
        "check_msg": "Starts with '/': absolute path, not a bare filename",
        "sanitize": lambda s, m: FNAME_MARK["SLASH"] + s[m:],
    },
]

def _apply_start_rules_for_check(name: str) -> List[Tuple[int, str]]:
    issues: List[Tuple[int, str]] = []
    for rule in START_RULES:
        m = rule["match_len"](name)
        if m:
            issues.append((0, rule["check_msg"]))
    return issues

def _apply_start_rules_for_sanitize(name: str) -> Optional[str]:
    out = name; changed = False
    for rule in START_RULES:
        m = rule["match_len"](out)
        if m:
            new_val = rule["sanitize"](out, m)
            if new_val is not None and new_val != out:
                out = new_val; changed = True
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

def bad_filename_sanitize(name: str) -> Optional[str]:
    """
    Sanitize filename using start rules, LF/CR truncation, and ASCII replacements.
    - At LF/CR: truncate at first and append EOL/CR token.
    - Apply start rules (lone '.' untouched).
    - Replace ALL dangerous ASCII anywhere (space is allowed), including '/' -> 'SLASH'.
    - If name is empty, DO NOT sanitize (return None).
    Returns None if no changes; otherwise the new name.
    """
    if name == "":
        return None  # empty is allowed; no auto-sanitize

    lf = name.find("\n"); cr = name.find("\r")
    if lf != -1 and (cr == -1 or lf < cr):
        return name[:lf] + FNAME_MARK["EOL"]
    if cr != -1:
        return name[:cr] + FNAME_MARK["CR"]

    changed = False
    out = name

    repl = _apply_start_rules_for_sanitize(out)
    if repl is not None:
        out = repl; changed = True

    parts: List[str] = []
    for ch in out:
        if ch in TOKENS_ALWAYS:
            parts.append(TOKENS_ALWAYS[ch]); changed = True
        elif ch in TOKENS_CONTEXTUAL:
            parts.append(TOKENS_CONTEXTUAL[ch]); changed = True
        else:
            parts.append(ch)

    out2 = "".join(parts)
    return None if not changed else out2
