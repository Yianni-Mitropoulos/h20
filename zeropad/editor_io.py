# editor_io.py
from __future__ import annotations

from pathlib import Path
import os
import codecs
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

# =============================================================================
# Raw file I/O
# =============================================================================

def read_text_bytes(path: Path | str) -> bytes:
    """Read raw bytes from disk."""
    return Path(path).read_bytes()

def save_to_path(path: Path | str, data: bytes) -> None:
    """
    Save bytes (create or truncate). This may create the file if missing
    and will update mtime/ctime as expected.
    """
    Path(path).write_bytes(data)

def overwrite_file_inplace(path: Path | str, data: bytes) -> None:
    """
    Overwrite an existing file's contents without recreating it.
    Keeps inode, mode bits, ownership, and xattrs (mtime updates).
    Raises FileNotFoundError if the target does not exist.
    """
    with open(path, "r+b") as f:
        f.seek(0)
        f.truncate(0)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

# =============================================================================
# Encoding helpers
# =============================================================================

# Canonical editor encoding list (ASCII removed on purpose).
_DEF_ENCODINGS = [
    "utf-8",
    "utf-8-with-bom",   # treated as a distinct label
    "utf-16-le",
    "utf-16-be",
    "latin-1",
    "windows-1252",
]

def _canonical_encoding(name: str) -> str:
    """Return Python's canonical codec name when possible."""
    try:
        return codecs.lookup(name).name
    except Exception:
        return (name or "").strip().lower()

def suggest_open_encoding(path: Path | str) -> str:
    """
    Trivial detector: if the file starts with UTF-8 BOM → 'utf-8-with-bom', else 'utf-8'.
    Extend here if you add chardet/uchardet later.
    """
    b = read_text_bytes(path)[:4]
    if b.startswith(b"\xef\xbb\xbf"):
        return "utf-8-with-bom"
    return "utf-8"

def decode_bytes(b: bytes, encoding: str, errors: str = "strict") -> str:
    """
    Decode bytes with unified BOM semantics:
      - 'utf-8-with-bom' uses Python's 'utf-8-sig' (strips BOM).
    """
    enc = (encoding or "").strip().lower()
    if enc == "utf-8-with-bom":
        return b.decode("utf-8-sig", errors=errors)
    return b.decode(encoding, errors=errors)

def encode_text(text: str, encoding: str, add_bom: bool | None = None) -> bytes:
    """
    Encode text, honoring 'utf-8-with-bom' as a real label.
    If add_bom is None, it is inferred from the encoding label.
    """
    enc = (encoding or "").strip().lower()

    # Infer BOM if not explicitly provided
    if add_bom is None:
        add_bom = (enc == "utf-8-with-bom")

    if enc in ("utf-8", "utf8", "utf-8-with-bom"):
        raw = text.encode("utf-8")
        if add_bom:
            return b"\xef\xbb\xbf" + raw
        return raw

    return text.encode(encoding)

# =============================================================================
# Simple “maybe” encoding chooser (when you want a quick confirm/override)
# =============================================================================

def maybe_choose_encoding(owner: tk.Misc,
                          suggest_encoding: str,
                          title: str,
                          body: str) -> tuple[str, str] | None:
    """
    Lightweight 2-step chooser:
      1) Ask to keep the suggested encoding.
      2) If not, prompt for another encoding string.
    Returns (encoding, errors) or None if cancelled.
    """
    enc_label = suggest_encoding or "utf-8"
    use_suggest = messagebox.askyesno(
        title, f"{body}\n\nUse {enc_label}?", parent=owner, default="yes"
    )
    if use_suggest:
        return (enc_label, "strict")

    new_enc = simpledialog.askstring(
        title,
        "Enter encoding (e.g. utf-8, utf-8-with-bom, latin-1, cp1252):",
        initialvalue=enc_label,
        parent=owner,
    )
    if not new_enc:
        return None
    # Normalize common aliases like cp1252 -> windows-1252
    norm = _canonical_encoding(new_enc).replace("cp1252", "windows-1252")
    # Preserve our special label if user typed it
    if new_enc.strip().lower() == "utf-8-with-bom":
        norm = "utf-8-with-bom"
    return (norm, "strict")

# =============================================================================
# Prompt for open encoding (API used by text panel)
# =============================================================================

def prompt_open_with_encoding(owner: tk.Misc, path: Path | str) -> tuple[str, str, bool]:
    """
    Suggest an encoding for opening `path`, allow override, and return:
      (encoding, errors, add_bom)
    For open, add_bom reflects whether the selected encoding implies BOM on save,
    i.e., True when encoding == 'utf-8-with-bom'.
    """
    suggest = suggest_open_encoding(path)
    res = maybe_choose_encoding(
        owner,
        suggest_encoding=suggest,
        title="Open — Encoding",
        body=f"Guessed encoding for:\n{path}",
    )
    if not res:
        # User cancelled; propagate a no-op by returning the suggestion with strict
        # semantics so caller can choose to abort based on UI flow. However, since
        # text_panel checks for a truthy result before proceeding, we can still
        # return a consistent triple and let the caller decide.
        return (suggest, "strict", suggest == "utf-8-with-bom")
    enc, errors = res
    return (enc, errors, enc.strip().lower() == "utf-8-with-bom")

# =============================================================================
# Theming helpers
# =============================================================================

def _apply_dark_combo_style(owner: tk.Misc, stylename="ZP.TCombobox"):
    """Dark-theme a ttk.Combobox field (note: dropdown list may follow system)."""
    pal = getattr(owner, "_palette", {})
    bg = pal.get("BG_PANEL", "#111827")
    fg = pal.get("FG_TEXT",  "#e5e7eb")
    style = ttk.Style(owner)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(stylename,
                    fieldbackground=bg,
                    background=bg,
                    foreground=fg,
                    arrowcolor=fg)
    style.map(stylename,
              fieldbackground=[("readonly", bg)],
              background=[("readonly", bg)],
              foreground=[("readonly", fg)])

# =============================================================================
# Save Over – inline encoding picker (one compact dialog)
# =============================================================================

def encode_text_inline(owner: tk.Misc, text: str, default_encoding: str) -> tuple[bytes, str]:
    """
    Modal encoding picker for 'Save Over'.
    Returns (data: bytes, encoding: str). Raises RuntimeError on cancel.
    """
    ENCODINGS = list(_DEF_ENCODINGS)

    pal = getattr(owner, "_palette", {})
    bg = pal.get("BG_PANEL", "#111827")
    fg = pal.get("FG_TEXT",  "#e5e7eb")

    win = tk.Toplevel(owner)
    win.withdraw()
    win.title("Save Over — Encoding")
    win.configure(bg=bg)
    win.transient(owner)
    win.grab_set()

    frm = tk.Frame(win, bg=bg)
    frm.pack(fill="both", expand=True, padx=16, pady=16)

    tk.Label(frm, text="Encoding:", bg=bg, fg=fg).grid(row=0, column=0, sticky="w")

    _apply_dark_combo_style(owner)
    enc_var = tk.StringVar(value=(default_encoding or "utf-8"))
    enc_box = ttk.Combobox(frm, textvariable=enc_var, values=ENCODINGS, state="readonly",
                           width=28, style="ZP.TCombobox")
    enc_box.grid(row=0, column=1, sticky="w", padx=(8, 0))

    btns = tk.Frame(frm, bg=bg)
    btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(14, 0))

    out: dict[str, tuple[bytes, str] | None] = {"res": None}

    def ok():
        enc = enc_var.get().strip() or (default_encoding or "utf-8")
        try:
            data = encode_text(text, enc)  # BOM inferred from label
        except Exception as e:
            messagebox.showerror("Encoding Error", f"Could not encode text:\n{e}", parent=win)
            return
        out["res"] = (data, enc)
        win.destroy()

    def cancel():
        out["res"] = None
        win.destroy()

    ttk.Button(btns, text="OK", command=ok).pack(side="right")
    ttk.Button(btns, text="Cancel", command=cancel).pack(side="right", padx=(0, 8))

    win.update_idletasks()
    try:
        px, py = owner.winfo_rootx(), owner.winfo_rooty()
        pw, ph = owner.winfo_width(), owner.winfo_height()
        ww, wh = max(420, win.winfo_reqwidth()), max(140, win.winfo_reqheight())
        x = px + max(0, (pw - ww) // 2)
        y = py + max(0, (ph - wh) // 3)
        win.geometry(f"{ww}x{wh}+{x}+{y}")
    except Exception:
        pass
    win.deiconify()
    win.lift()
    win.focus_set()
    win.wait_window()

    if out["res"] is None:
        raise RuntimeError("Canceled")
    return out["res"]

# =============================================================================
# Save As – single dialog with embedded encoding selector
# =============================================================================

def prompt_save_as_with_encoding(owner: tk.Misc,
                                 suggest_path: Path | None,
                                 suggest_enc: str,
                                 suggest_bom: bool) -> tuple[Path, str, str, bool] | None:
    """
    'Save As' dialog with an inline encoding combobox.
    Returns (path: Path, encoding: str, errors: str, add_bom: bool) or None.
    If suggest_bom is True and suggest_enc is a UTF-8 variant, we preselect 'utf-8-with-bom'.
    """
    ENCODINGS = list(_DEF_ENCODINGS)

    pal = getattr(owner, "_palette", {})
    bg = pal.get("BG_PANEL", "#111827")
    fg = pal.get("FG_TEXT",  "#e5e7eb")

    # Derive default encoding selection
    enc_default = (suggest_enc or "utf-8").strip().lower()
    if suggest_bom and enc_default in ("utf-8", "utf8", "utf-8-with-bom"):
        enc_default = "utf-8-with-bom"

    win = tk.Toplevel(owner)
    win.withdraw()
    win.title("Save As")
    win.configure(bg=bg)
    win.transient(owner)
    win.grab_set()

    frm = tk.Frame(win, bg=bg)
    frm.pack(fill="both", expand=True, padx=16, pady=16)

    # Path row
    tk.Label(frm, text="File:", bg=bg, fg=fg).grid(row=0, column=0, sticky="w")
    path_var = tk.StringVar(value=(str(suggest_path) if suggest_path else ""))
    entry = tk.Entry(frm, textvariable=path_var, bg="#0b1220", fg=fg,
                     insertbackground=fg, relief="flat", width=48)
    entry.grid(row=0, column=1, sticky="we", padx=(8, 0))
    frm.grid_columnconfigure(1, weight=1)

    def browse():
        initfile = suggest_path.name if suggest_path else "untitled.txt"
        fname = filedialog.asksaveasfilename(parent=owner, initialfile=initfile)
        if fname:
            path_var.set(fname)

    ttk.Button(frm, text="Browse…", command=browse).grid(row=0, column=2, sticky="w", padx=(8, 0))

    # Encoding row
    tk.Label(frm, text="Encoding:", bg=bg, fg=fg).grid(row=1, column=0, sticky="w", pady=(10, 0))
    _apply_dark_combo_style(owner)
    enc_var = tk.StringVar(value=enc_default or "utf-8")
    enc_box = ttk.Combobox(frm, textvariable=enc_var, values=ENCODINGS,
                           state="readonly", width=28, style="ZP.TCombobox")
    enc_box.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

    # Buttons
    btns = tk.Frame(frm, bg=bg)
    btns.grid(row=2, column=0, columnspan=3, sticky="e", pady=(14, 0))
    out: dict[str, tuple[Path, str, str, bool] | None] = {"res": None}

    def ok():
        p = path_var.get().strip()
        if not p:
            messagebox.showerror("Save As", "Please choose a file path.", parent=win)
            return
        enc = enc_var.get().strip() or "utf-8"
        add_bom = (enc.lower() == "utf-8-with-bom")
        out["res"] = (Path(p), enc, "strict", add_bom)
        win.destroy()

    def cancel():
        out["res"] = None
        win.destroy()

    ttk.Button(btns, text="OK", command=ok).pack(side="right")
    ttk.Button(btns, text="Cancel", command=cancel).pack(side="right", padx=(0, 8))

    # Sizing/placement
    win.update_idletasks()
    try:
        px, py = owner.winfo_rootx(), owner.winfo_rooty()
        pw, ph = owner.winfo_width(), owner.winfo_height()
        ww, wh = 600, 200
        x = px + max(0, (pw - ww) // 2)
        y = py + max(0, (ph - wh) // 3)
        win.geometry(f"{ww}x{wh}+{x}+{y}")
    except Exception:
        pass

    win.deiconify()
    win.lift()
    win.focus_set()
    win.wait_window()
    return out["res"]

# =============================================================================
# Integrated “Open Selected” chooser (system vs Zeropad)
# =============================================================================

def choose_open_selected(owner: tk.Misc, path: Path) -> str | None:
    """
    Ask how to open the selected file:
      - None         → Cancel
      - "system"     → Open with system default
      - "zeropad"    → Open in editor with encoding choice
    Uses a deferred grab to avoid 'grab failed' races on some WMs.
    """
    BG = getattr(owner, "_palette", {}).get("BG_PANEL", "#111827")
    FG = getattr(owner, "_palette", {}).get("FG_TEXT", "#e5e7eb")
    BTN_BG = "#1f2937"
    BTN_BG_H = "#374151"

    win = tk.Toplevel(owner)
    win.withdraw()
    win.title("Open Selected")
    win.configure(bg=BG)
    win.transient(owner)
    win.resizable(False, False)

    style = ttk.Style(owner)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Dlg.TButton", background=BTN_BG, foreground=FG, padding=(10, 4), borderwidth=0)
    style.map("Dlg.TButton",
              background=[("active", BTN_BG_H)],
              foreground=[("disabled", "#9ca3af")])

    tk.Label(win, text="You've selected the following file for opening:", bg=BG, fg=FG, anchor="w").pack(
        side="top", fill="x", padx=14, pady=(14, 6)
    )
    tk.Label(win, text=str(path), bg=BG, fg=FG, anchor="w", justify="left", wraplength=640).pack(
        side="top", fill="x", padx=14, pady=(0, 10)
    )

    btns = tk.Frame(win, bg=BG)
    btns.pack(side="top", fill="x", padx=14, pady=(0, 14))

    choice: dict[str, str | None] = {"val": None}

    def _close():
        if win.winfo_exists():
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

    def on_cancel():   choice.update(val=None);      _close()
    def on_system():   choice.update(val="system");  _close()
    def on_zeropad():  choice.update(val="zeropad"); _close()

    ttk.Button(btns, text="Cancel", style="Dlg.TButton", command=on_cancel).pack(side="right")
    ttk.Button(btns, text="Open with System Default", style="Dlg.TButton", command=on_system).pack(side="right", padx=(0, 8))
    ttk.Button(btns, text="Open in Zeropad", style="Dlg.TButton", command=on_zeropad).pack(side="right", padx=(0, 8))

    win.bind("<Escape>", lambda e: on_cancel())
    win.protocol("WM_DELETE_WINDOW", on_cancel)

    win.update_idletasks()
    try:
        ox, oy = owner.winfo_rootx(), owner.winfo_rooty()
        ow, oh = owner.winfo_width(), owner.winfo_height()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        x = ox + max(0, (ow - ww) // 2)
        y = oy + max(0, (oh - wh) // 3)
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    win.deiconify()
    win.lift()

    def _try_grab():
        if not win.winfo_exists():
            return
        if not win.winfo_viewable():
            win.after(15, _try_grab)
            return
        try:
            win.grab_set()
        except tk.TclError:
            win.after(15, _try_grab)

    win.after(0, _try_grab)
    try:
        win.wait_window()
    except tk.TclError:
        return None

    return choice["val"]
