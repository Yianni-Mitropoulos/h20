# editor_io.py
"""
Zeropad: File I/O helpers (OPEN / SAVE / SAVE AS) with encoding & BOM handling.

Goals
=====
- Decode bytes using a sensible detector:
  * Honor BOMs first (UTF-8/16/32 LE/BE)
  * Else try UTF-8 strict
  * Else try common single-byte fallbacks (Windows-1252, ISO-8859-1)
- Let the user confirm/override encoding BEFORE load via a modal dialog.
- Normalize EOLs in the editor buffer: CRLF→LF, lone CR→LF.
- Remember encoding + "write BOM" for saves (Save, Save As).
- Keep UI here; leave tab creation / dirty tracking to TextPanel.

Public API (call from main/TextPanel/FilePanel)
===============================================
- choose_encoding_and_read(parent, path: Path) -> (text:str, meta:dict)
    meta keys:
      encoding: str                 # canonical Python codec name (e.g. 'utf-8', 'utf-16-le')
      write_bom: bool               # whether to emit a BOM on save
      had_bom: bool                 # whether the source had a BOM
      eol_style: str                # 'lf'|'crlf'|'cr' (source heuristic)
      byte_length: int              # size on disk
- write_text_to_path(path: Path, text: str, *, encoding: str, write_bom: bool) -> None
    (Replaces file content. Always writes '\n' newlines.)
- save_as_dialog(parent, initial_path: Path, text: str, *, encoding: str, write_bom: bool)
    -> Optional[tuple[Path, str, bool]]
    (Shows a Save As dialog; writes the file; returns (new_path, encoding, write_bom) or None.)

Wiring sketch (minimal)
=======================
- File panel: on “Open in Zeropad”
    text, meta = choose_encoding_and_read(self, path)
    self.text_open_document(path, text, meta)  # implement in TextPanel

- Text panel: on “Save”
    write_text_to_path(tab.path, text_widget.get("1.0","end-1c"),
                       encoding=tab.meta['encoding'],
                       write_bom=tab.meta['write_bom'])

- Text panel: on “Save As”
    rv = save_as_dialog(self, Path(tab.path), text_widget.get(...),
                        encoding=tab.meta['encoding'],
                        write_bom=tab.meta['write_bom'])
    if rv: (new_path, new_enc, new_bom) = rv; update tab metadata/UI.
"""

from __future__ import annotations

import binascii
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ------------------------------ BOM tables ------------------------------

@dataclass(frozen=True)
class _BOMInfo:
    name: str
    bytes_: bytes
    py_codec: str   # canonical Python codec to decode remaining bytes (after BOM)

# Order matters: longest first
_BOMS: tuple[_BOMInfo, ...] = (
    _BOMInfo("UTF-32-BE", b"\x00\x00\xFE\xFF", "utf-32-be"),
    _BOMInfo("UTF-32-LE", b"\xFF\xFE\x00\x00", "utf-32-le"),
    _BOMInfo("UTF-16-BE", b"\xFE\xFF",          "utf-16-be"),
    _BOMInfo("UTF-16-LE", b"\xFF\xFE",          "utf-16-le"),
    _BOMInfo("UTF-8-BOM", b"\xEF\xBB\xBF",      "utf-8"),
)

_UTF_WRITE_BOMS = {
    "utf-8":     b"\xEF\xBB\xBF",
    "utf-16-be": b"\xFE\xFF",
    "utf-16-le": b"\xFF\xFE",
    "utf-32-be": b"\x00\x00\xFE\xFF",
    "utf-32-le": b"\xFF\xFE\x00\x00",
}

# sensible fallbacks (only if no BOM and UTF-8 fails)
_FALLBACK_SINGLE_BYTE = ("windows-1252", "iso-8859-1")


# ------------------------------ helpers ------------------------------

def _detect_eol_style(raw: bytes) -> str:
    """Return 'crlf'|'lf'|'cr' based on first newline style seen; default 'lf'."""
    if b"\r\n" in raw:
        return "crlf"
    if b"\r" in raw and b"\n" not in raw:
        return "cr"
    return "lf"


def _strip_bom(raw: bytes) -> Tuple[bytes, Optional[_BOMInfo]]:
    """Remove leading BOM if present; return (remaining_bytes, bominfo_or_None)."""
    for info in _BOMS:
        if raw.startswith(info.bytes_):
            return raw[len(info.bytes_):], info
    return raw, None


def _normalize_eols(text: str) -> str:
    """CRLF→LF, lone CR→LF."""
    # order matters: collapse CRLF first, then any stray CR
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    return text


def _try_decode(raw: bytes, encodings: Iterable[str]) -> Optional[Tuple[str, str]]:
    """Try candidate encodings; return (encoding_used, text) or None."""
    for enc in encodings:
        try:
            return enc, raw.decode(enc, errors="strict")
        except Exception:
            continue
    return None


def _canonical_encoding_name(enc: str) -> str:
    """Normalize a few alias spellings."""
    enc = enc.lower().replace("_", "-")
    if enc in {"utf8", "utf-8-sig"}:
        return "utf-8"
    if enc in {"ucs-2-le", "utf16le"}:
        return "utf-16-le"
    if enc in {"ucs-2-be", "utf16be"}:
        return "utf-16-be"
    if enc in {"utf32le"}:
        return "utf-32-le"
    if enc in {"utf32be"}:
        return "utf-32-be"
    return enc


# ------------------------------ OPEN: choose encoding & read ------------------------------

def choose_encoding_and_read(parent: tk.Misc, path: Path) -> Tuple[str, dict]:
    """
    Modal chooser that proposes an encoding, lets the user override, and returns
    normalized text + metadata.

    Returns:
      text: str  (EOL-normalized to LF)
      meta: dict with keys:
        - encoding: str
        - write_bom: bool
        - had_bom: bool
        - eol_style: 'lf'|'crlf'|'cr'  (source heuristic)
        - byte_length: int
    """
    raw = path.read_bytes()
    byte_length = len(raw)
    eol_style = _detect_eol_style(raw)

    # 1) BOM?
    body, bom = _strip_bom(raw)
    if bom:
        # Use the BOM’s codec; suggest writing a BOM again on save
        probe = _try_decode(body, (bom.py_codec,))
        if probe:
            suggested_encoding, text = probe
            suggested_write_bom = True
        else:
            # Extremely rare: BOM present but decode fails. Fall back to raw decode showing hex preview.
            suggested_encoding, text = bom.py_codec, body.decode(bom.py_codec, errors="replace")
            suggested_write_bom = True
    else:
        # 2) No BOM → try UTF-8 strict, then single-byte fallbacks
        probe = _try_decode(raw, ("utf-8",))
        if probe:
            suggested_encoding, text = probe
            suggested_write_bom = False
        else:
            probe = _try_decode(raw, _FALLBACK_SINGLE_BYTE)
            if probe:
                suggested_encoding, text = probe
                suggested_write_bom = False
            else:
                # Last resort: show Latin-1 replacement so dialog can still open
                suggested_encoding, text = "windows-1252", raw.decode("windows-1252", errors="replace")
                suggested_write_bom = False

    # Open modal dialog to confirm/change encoding
    enc, write_bom = _encoding_dialog(parent, path, raw, suggested_encoding, suggested_write_bom)

    # Decode with chosen encoding (strict); we already validated inside dialog
    text = raw.decode(enc, errors="strict")
    text = _normalize_eols(text)
    meta = dict(
        encoding=enc,
        write_bom=bool(write_bom),
        had_bom=bool(bom is not None),
        eol_style=eol_style,
        byte_length=byte_length,
    )
    return text, meta


def _encoding_dialog(parent: tk.Misc, path: Path, raw: bytes,
                     suggested_encoding: str, suggested_write_bom: bool) -> Tuple[str, bool]:
    """
    Modal dialog to pick encoding + BOM. Provides live preview; prevents OK if decode fails.
    Returns (encoding:str, write_bom:bool).
    """
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(f"Open: {path.name}")
    win.configure(bg=_bg(parent))
    win.transient(parent)

    # ---- UI bits
    frm = tk.Frame(win, bg=_bg(parent))
    frm.pack(fill="both", expand=True, padx=12, pady=12)

    # Row 0: path + size
    tk.Label(frm, text=str(path), anchor="w", bg=_bg(parent), fg=_fg(parent)).grid(row=0, column=0, columnspan=3, sticky="ew")
    try:
        import os
        sz = os.path.getsize(path)
        size_str = f"{sz} bytes"
    except Exception:
        size_str = "unknown size"
    tk.Label(frm, text=size_str, anchor="w", bg=_bg(parent), fg=_dim(parent)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))

    # Row 2: encoding dropdown + BOM checkbox
    tk.Label(frm, text="Encoding", bg=_bg(parent), fg=_fg(parent)).grid(row=2, column=0, sticky="w")
    enc_var = tk.StringVar(value=_canonical_encoding_name(suggested_encoding))
    enc_combo = ttk.Combobox(frm, textvariable=enc_var, width=32, values=_encoding_list(), state="readonly")
    enc_combo.grid(row=2, column=1, sticky="w", padx=(6, 0))

    bom_var = tk.BooleanVar(value=bool(suggested_write_bom))
    bom_box = ttk.Checkbutton(frm, text="Write BOM on save", variable=bom_var)
    bom_box.grid(row=2, column=2, sticky="w", padx=(12, 0))

    # Row 3: preview (scrollable)
    preview = tk.Text(frm, width=100, height=16, bg=_panel(parent), fg=_fg(parent),
                      insertbackground=_fg(parent), relief="flat", wrap="none")
    yscroll = ttk.Scrollbar(frm, orient="vertical", command=preview.yview)
    preview.configure(yscrollcommand=yscroll.set)
    preview.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    yscroll.grid(row=3, column=3, sticky="ns", pady=(8, 0))
    frm.grid_rowconfigure(3, weight=1)
    frm.grid_columnconfigure(0, weight=1)

    # Row 4: status + buttons
    status = tk.Label(frm, text="", anchor="w", bg=_bg(parent), fg=_dim(parent))
    status.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

    btns = tk.Frame(frm, bg=_bg(parent))
    btns.grid(row=4, column=2, sticky="e", pady=(6, 0))
    ok_btn = ttk.Button(btns, text="Open")
    cancel_btn = ttk.Button(btns, text="Cancel", command=lambda: _close_dialog(win, None))
    cancel_btn.pack(side="right")
    ok_btn.pack(side="right", padx=(0, 8))

    # live decode + preview
    def refresh_preview(*_):
        enc = _canonical_encoding_name(enc_var.get())
        # BOM checkbox is meaningful for UTFs only
        bom_box.state(["!disabled"] if enc.startswith("utf-") else ["disabled"])
        try:
            txt = raw.decode(enc, errors="strict")
            shown = _normalize_eols(txt[:100_000])  # cap preview for performance
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            preview.insert("1.0", shown)
            preview.configure(state="disabled")
            status.config(text=f"Preview OK — encoding={enc}")
            ok_btn.config(state="normal")
        except Exception as e:
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            preview.insert("1.0", f"(cannot decode with {enc})\n\n{e}")
            preview.configure(state="disabled")
            status.config(text=f"Decoding failed with {enc}")
            ok_btn.config(state="disabled")

    enc_combo.bind("<<ComboboxSelected>>", refresh_preview)

    def do_ok():
        enc = _canonical_encoding_name(enc_var.get())
        # Validate one last time
        try:
            raw.decode(enc, errors="strict")
        except Exception as e:
            messagebox.showerror("Cannot decode", f"{enc}\n\n{e}", parent=win)
            return
        _close_dialog(win, (enc, bool(bom_var.get())))

    ok_btn.config(command=do_ok)

    # map & center
    win.update_idletasks()
    _center_like(parent, win)
    win.deiconify()
    win.lift()

    # take grab after mapped
    def _try_grab():
        if win.winfo_viewable():
            try:
                win.grab_set()
            except Exception:
                win.after(10, _try_grab)
        else:
            win.after(10, _try_grab)
    _try_grab()

    win.bind("<Escape>", lambda e: _close_dialog(win, None))
    enc_combo.focus_set()
    refresh_preview()
    rv = _wait_modal(win)
    if rv is None:
        raise RuntimeError("Open canceled by user")
    enc, write_bom = rv
    return enc, bool(write_bom)


# ------------------------------ SAVE / SAVE AS ------------------------------

def write_text_to_path(path: Path, text: str, *, encoding: str, write_bom: bool) -> None:
    """
    Write text to path with the given encoding and optional BOM.
    The editor buffer is assumed EOL-normalized to LF (\\n), and we keep it that way.
    """
    enc = _canonical_encoding_name(encoding)
    data = text.encode(enc, errors="strict")
    if write_bom and enc in _UTF_WRITE_BOMS:
        data = _UTF_WRITE_BOMS[enc] + data
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp~")
    tmp.write_bytes(data)
    tmp.replace(path)


def save_as_dialog(parent: tk.Misc, initial_path: Path, text: str, *,
                   encoding: str, write_bom: bool) -> Optional[Tuple[Path, str, bool]]:
    """
    Show a Save As dialog. If the user picks a path:
      - Ask whether to change encoding/BOM via a small modal.
      - Write the file.
      - Return (new_path, encoding, write_bom).
    Else return None.
    """
    filename = filedialog.asksaveasfilename(
        parent=parent,
        title="Save As",
        initialdir=str(initial_path.parent if initial_path else Path.home()),
        initialfile=(initial_path.name if initial_path else ""),
    )
    if not filename:
        return None
    dest = Path(filename)

    enc, bom = _save_encoding_dialog(parent, encoding, write_bom)
    write_text_to_path(dest, text, encoding=enc, write_bom=bom)
    return dest, enc, bom


def _save_encoding_dialog(parent: tk.Misc, current_encoding: str, current_bom: bool) -> Tuple[str, bool]:
    """Small modal asking to confirm/adjust encoding & BOM before writing."""
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title("Save Options")
    win.configure(bg=_bg(parent))
    win.transient(parent)

    frm = tk.Frame(win, bg=_bg(parent))
    frm.pack(fill="both", expand=True, padx=12, pady=12)

    tk.Label(frm, text="Encoding", bg=_bg(parent), fg=_fg(parent)).grid(row=0, column=0, sticky="w")
    enc_var = tk.StringVar(value=_canonical_encoding_name(current_encoding))
    enc_combo = ttk.Combobox(frm, textvariable=enc_var, width=32, values=_encoding_list(), state="readonly")
    enc_combo.grid(row=0, column=1, sticky="w", padx=(6, 0))

    bom_var = tk.BooleanVar(value=bool(current_bom))
    bom_box = ttk.Checkbutton(frm, text="Write BOM", variable=bom_var)
    bom_box.grid(row=0, column=2, sticky="w", padx=(12, 0))

    def on_enc_change(*_):
        enc = _canonical_encoding_name(enc_var.get())
        bom_box.state(["!disabled"] if enc.startswith("utf-") else ["disabled"])
    enc_combo.bind("<<ComboboxSelected>>", on_enc_change)
    on_enc_change()

    btns = tk.Frame(frm, bg=_bg(parent))
    btns.grid(row=1, column=0, columnspan=3, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Cancel", command=lambda: _close_dialog(win, None)).pack(side="right")
    ttk.Button(btns, text="Save", command=lambda: _close_dialog(win, (_canonical_encoding_name(enc_var.get()),
                                                                      bool(bom_var.get())))).pack(side="right", padx=(0, 8))

    win.update_idletasks()
    _center_like(parent, win)
    win.deiconify()
    win.lift()

    def _try_grab():
        if win.winfo_viewable():
            try: win.grab_set()
            except Exception: win.after(10, _try_grab)
        else:
            win.after(10, _try_grab)
    _try_grab()

    win.bind("<Escape>", lambda e: _close_dialog(win, None))
    enc_combo.focus_set()
    rv = _wait_modal(win)
    if rv is None:
        raise RuntimeError("Save canceled by user")
    return rv


# ------------------------------ UI utilities ------------------------------

def _bg(w: tk.Misc) -> str:
    return getattr(getattr(w, "_palette", None), "get", lambda *_: "#0b1220")("BG")  # type: ignore

def _panel(w: tk.Misc) -> str:
    return getattr(getattr(w, "_palette", None), "get", lambda *_: "#111827")("BG_PANEL")  # type: ignore

def _fg(w: tk.Misc) -> str:
    return getattr(getattr(w, "_palette", None), "get", lambda *_: "#e5e7eb")("FG_TEXT")  # type: ignore

def _dim(w: tk.Misc) -> str:
    return "#9ca3af"

def _center_like(parent: tk.Misc, win: tk.Toplevel) -> None:
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        x = px + max(0, (pw - ww) // 2)
        y = py + max(0, (ph - wh) // 3)
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

def _wait_modal(win: tk.Toplevel):
    rv_container = {"rv": None}
    def _setter(val): rv_container["rv"] = val
    win._editorio_rv = _setter  # type: ignore[attr-defined]
    win.wait_window()
    return rv_container["rv"]

def _close_dialog(win: tk.Toplevel, rv):
    # store rv and destroy
    try:
        setter = getattr(win, "_editorio_rv")  # type: ignore[attr-defined]
        if callable(setter):
            setter(rv)
    except Exception:
        pass
    try:
        win.grab_release()
    except Exception:
        pass
    win.destroy()

def _encoding_list() -> list[str]:
    """Common choices first; editable later if needed."""
    return [
        "utf-8",
        "utf-16-le", "utf-16-be",
        "utf-32-le", "utf-32-be",
        "windows-1252", "iso-8859-1",
        "shift-jis", "euc-jp",
        "gb18030",
        "koi8-r",
        "mac-roman",
    ]
