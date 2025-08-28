#!/usr/bin/env python3
import os
import re
from pathlib import Path
from typing import List, Dict, Optional


# ====================================================================
# Template loader
# ====================================================================
class Templates:
    def __init__(self, base: Path):
        self.shell = (base / "HTML_SHELL.html").read_text(encoding="utf-8")
        self.page = (base / "PAGE_TMPL.html").read_text(encoding="utf-8")

        # Elements
        self.tpl_paragraph = (base / "element_paragraph.html").read_text(encoding="utf-8")
        self.tpl_olist = (base / "element_ordered_list.html").read_text(encoding="utf-8")
        self.tpl_ulist = (base / "element_unordered_list.html").read_text(encoding="utf-8")
        self.tpl_input = (base / "element_input_field.html").read_text(encoding="utf-8")

        # Code (language-specific) — only bash is needed
        self.tpl_bash = (base / "element_bash.html").read_text(encoding="utf-8")

    def code_tpl_for(self, lang: str) -> str:
        key = (lang or "").lower()
        if key == "bash":
            return self.tpl_bash
        raise RuntimeError(f"No template for code type '{lang}'")


# ====================================================================
# Indent-aware interpolation (with <pre> protection)
# ====================================================================
_LINE_ONLY_PH = re.compile(r'^([ \t]*)\{([A-Za-z0-9_]+)\}[ \t]*\r?$', re.MULTILINE)

class _SafeDict(dict):
    def __missing__(self, k):  # leave unknown placeholders intact
        return '{' + k + '}'


def _escape_code_html(s: str) -> str:
    # Only used for bash code payloads
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _replace_full_line_placeholder_no_newline_consume(template: str, key: str, payload: str) -> str:
    """
    Replace a line consisting solely of indentation + {key} + optional spaces,
    but DO NOT consume the template's newline. This avoids extra blank lines inside <pre>.
    """
    pat = re.compile(rf'^([ \t]*)\{{{re.escape(key)}\}}[ \t]*$', re.MULTILINE)
    return pat.sub(lambda m: payload, template)


def _pre_sensitive_indent(value: str, indent: str) -> str:
    """
    Add 'indent' to all lines except those inside <pre>...</pre> blocks.
    Lines within <pre> blocks (including <pre> and </pre>) are emitted without added indent.
    """
    out: List[str] = []
    in_pre = False
    for raw in value.splitlines(True):  # keep newlines
        line = raw.rstrip("\n\r")
        nl = raw[len(line):]
        stripped = line.lstrip()
        if stripped.startswith("<pre"):
            in_pre = True
            out.append(stripped + nl)  # leftmost
            continue
        if stripped.startswith("</pre"):
            out.append(stripped + nl)  # leftmost
            in_pre = False
            continue
        if in_pre:
            out.append(line + nl)      # keep as-is
        else:
            out.append((indent + line if line else "") + nl)
    return "".join(out)


def indent_aware_format(template: str, mapping: Dict[str, str]) -> str:
    """
    If a placeholder stands alone on a line, indent the inserted multiline value to match the line's
    indentation — EXCEPT for content inside <pre> blocks, which must remain leftmost.

    After handling full-line placeholders, do a normal inline .format_map for the rest.
    """
    lines = template.splitlines(True)  # preserve newlines
    out: List[str] = []

    for raw in lines:
        m = re.match(r'^([ \t]*)\{([A-Za-z0-9_]+)\}[ \t]*\r?\n?$', raw)
        if m:
            indent, key = m.group(1), m.group(2)
            if key in mapping:
                val = mapping[key]
                if key in ("body", "pages_html"):
                    out.append(_pre_sensitive_indent(val, indent))
                else:
                    for v in val.splitlines(True):
                        out.append((indent + v) if v.strip() else v)
                continue
        out.append(raw)

    templ2 = "".join(out)
    return templ2.format_map(_SafeDict(mapping))


# ====================================================================
# Element renderers  (ONLY bash code escapes; others are raw)
# ====================================================================
def render_paragraph(tpl: str, lines: List[str]) -> str:
    # Inject raw (no escaping)
    text = " ".join(line.strip() for line in lines if line.strip())
    return tpl.replace("{text}", text)


def render_list(tpl: str, lines: List[str]) -> str:
    # Lines are already <li>...</li> — inject as-is
    items = "\n".join(lines).rstrip()
    return tpl.replace("{items}", items)


def _align_pre_left(s: str) -> str:
    """
    Ensure <pre> and </pre> lines themselves are at column 0,
    regardless of any indentation in the element template.
    """
    out: List[str] = []
    for raw in s.splitlines(True):
        line = raw.rstrip("\n\r")
        nl = raw[len(line):]
        if line.lstrip().startswith("<pre") or line.lstrip().startswith("</pre"):
            out.append(line.lstrip() + nl)
        else:
            out.append(raw)
    return "".join(out)


def render_code(code_tpl: str, code_lines: List[str]) -> str:
    # Escape &, <, > ONLY for code
    code_raw = "\n".join(code_lines).rstrip()
    code_html = _escape_code_html(code_raw)
    # Replace {code} without consuming the newline in the template
    inserted = _replace_full_line_placeholder_no_newline_consume(code_tpl, "code", code_html)
    # Normalize <pre> lines to leftmost
    return _align_pre_left(inserted)


def render_input(tpl: str, input_id: str, lines: List[str]) -> str:
    # Inject raw (no escaping). NOTE: quotes or < > in placeholder will be literal.
    placeholder = " ".join(line.strip() for line in lines if line.strip())
    return (tpl
            .replace("{id}", input_id)
            .replace("{placeholder}", placeholder or input_id))


# ====================================================================
# DSL parser
# ====================================================================
RE_EQ_ONLY      = re.compile(r"^\s*=+\s*$")
RE_PAGE_TITLE   = re.compile(r"^\s*===\s*(.*?)\s*===\s*$")
RE_ELEM_HEADER  = re.compile(r"^\s*@\s*(.+?)\s*$", re.I)
RE_INPUT_HDR    = re.compile(r"^\s*input\s+field\s*\(\s*([^)]+)\s*\)\s*$", re.I)
RE_PARA_HDR     = re.compile(r"^\s*paragraph\s*$", re.I)
RE_OLIST_HDR    = re.compile(r"^\s*ordered\s+list\s*$", re.I)
RE_ULIST_HDR    = re.compile(r"^\s*unordered\s+list\s*$", re.I)
RE_LANG_HDR     = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*$")  # e.g., bash


def parse_source(path: Path) -> List[Dict]:
    """
    Returns: [ { "title": str, "elements": [ {"kind", "param", "lines": [...]}, ... ] }, ... ]
    Rules:
      - '='-only lines ignored.
      - Page title: '=== Title ==='
      - No implicit element: content before @-header => error.
    """
    pages: List[Dict] = []
    current_page: Optional[Dict] = None
    current_el: Optional[Dict] = None

    def close_current_element():
        nonlocal current_el, current_page
        if current_el is None:
            return
        while current_el["lines"] and not current_el["lines"][-1].strip():
            current_el["lines"].pop()
        current_page["elements"].append(current_el)
        current_el = None

    with path.open(encoding="utf-8") as f:
        for idx, raw in enumerate(f, start=1):
            line = raw.rstrip("\n\r")

            if RE_EQ_ONLY.match(line):
                continue

            mtitle = RE_PAGE_TITLE.match(line)
            if mtitle:
                close_current_element()
                current_page = {"title": mtitle.group(1), "elements": []}
                pages.append(current_page)
                continue

            mheader = RE_ELEM_HEADER.match(line)
            if mheader:
                if current_page is None:
                    raise SyntaxError(f"{path}:{idx}: element header before any page title")
                spec = mheader.group(1)

                close_current_element()

                if RE_PARA_HDR.match(spec):
                    current_el = {"kind": "paragraph", "param": None, "lines": []}
                elif RE_OLIST_HDR.match(spec):
                    current_el = {"kind": "olist", "param": None, "lines": []}
                elif RE_ULIST_HDR.match(spec):
                    current_el = {"kind": "ulist", "param": None, "lines": []}
                else:
                    minput = RE_INPUT_HDR.match(spec)
                    if minput:
                        ident = minput.group(1)
                        if re.search(r"\s", ident):
                            raise SyntaxError(f"{path}:{idx}: input field parameter must not contain whitespace: '{ident}'")
                        current_el = {"kind": "input", "param": ident, "lines": []}
                    else:
                        mlang = RE_LANG_HDR.match(spec)   # e.g., @ bash
                        if not mlang:
                            raise SyntaxError(f"{path}:{idx}: unknown element header: '{spec}'")
                        current_el = {"kind": "code", "param": mlang.group(1), "lines": []}
                continue

            # Content
            if line.strip():
                if current_el is None:
                    raise SyntaxError(f"{path}:{idx}: content before element header")
                current_el["lines"].append(line)
            else:
                if current_el is not None:
                    current_el["lines"].append(line)

    close_current_element()

    if not pages:
        raise SyntaxError(f"{path}: no pages found (missing '=== Title ===')")
    return pages


# ====================================================================
# Assembler
# ====================================================================
def assemble_html(tpl: Templates, pages: List[Dict], site_title: str) -> str:
    page_divs: List[str] = []
    total = len(pages)

    for i, p in enumerate(pages):
        prev_attrs = 'disabled aria-disabled="true"' if i == 0 else 'aria-disabled="false"'
        next_attrs = 'disabled aria-disabled="true"' if i == total - 1 else 'aria-disabled="false"'

        body_parts: List[str] = []
        for el in p["elements"]:
            k = el["kind"]
            if k == "paragraph":
                body_parts.append(render_paragraph(tpl.tpl_paragraph, el["lines"]))
            elif k == "olist":
                body_parts.append(render_list(tpl.tpl_olist, el["lines"]))
            elif k == "ulist":
                body_parts.append(render_list(tpl.tpl_ulist, el["lines"]))
            elif k == "code":
                code_tpl = tpl.code_tpl_for(el["param"])
                body_parts.append(render_code(code_tpl, el["lines"]))
            elif k == "input":
                body_parts.append(render_input(tpl.tpl_input, el["param"], el["lines"]))
            else:
                raise RuntimeError(f"Unknown element kind: {k}")

        # NOTE: title injected raw (not escaped)
        page_html = indent_aware_format(tpl.page, {
            "format_attr": "",
            "title": p["title"],
            "prev_attrs": prev_attrs,
            "next_attrs": next_attrs,
            "body": "\n".join(body_parts),
        })
        page_divs.append(page_html)

    pages_html = "\n".join(page_divs)
    if not pages_html.endswith("\n"):
        pages_html += "\n"  # ensure the script tag in the shell sits on its own line

    # site_title injected raw (not escaped)
    return indent_aware_format(tpl.shell, {
        "title": site_title,
        "pages_html": pages_html,
    })


# ====================================================================
# Main
# ====================================================================
def main():
    cwd = Path(os.getcwd())
    src_root = cwd / "source_code"
    tgt_root = cwd / "target_code"
    tpldir = cwd / "templates"

    tpl = Templates(tpldir)
    tgt_root.mkdir(parents=True, exist_ok=True)

    # Recurse through source; mirror directory tree in target
    for src in sorted(src_root.rglob("*.txt")):
        pages = parse_source(src)
        title = pages[0]["title"] if pages and pages[0]["title"] else src.stem
        html_out = assemble_html(tpl, pages, site_title=title)

        rel = src.relative_to(src_root)
        out_path = tgt_root / rel.with_suffix(".html")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_out, encoding="utf-8")
        print(f"[OK] {src} -> {out_path}")


if __name__ == "__main__":
    main()
