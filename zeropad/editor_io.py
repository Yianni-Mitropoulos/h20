# editor_io.py
from __future__ import annotations
from pathlib import Path
import codecs
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

# -------------------------
# Core file I/O primitives
# -------------------------

def read_text_bytes(path: Path | str) -> bytes:
    """Read raw bytes (no decoding)."""
    return Path(path).read_bytes()

def save_to_path(path: Path | str, data: bytes) -> None:
    """Save bytes (create or truncate). This may change metadata like mtime."""
    Path(path).write_bytes(data)

def overwrite_file_inplace(path: Path | str, data: bytes) -> None:
    """
    Overwrite an existing file's contents in-place (truncate/write) without recreating it.
    - Keeps ownership, mode bits, xattrs, etc. (mtime will update as expected).
    """
    with open(path, "wb") as f:
        f.write(data)

# -------------------------
# Encoding helpers
# -------------------------

def _canonical_encoding(name: str) -> str:
    try:
        return codecs.lookup(name).name
    except Exception:
        return name.strip()

def decode_bytes(b: bytes, encoding: str, errors: str = "strict") -> str:
    return b.decode(encoding, errors=errors)

# -------------------------
# Lightweight UI helpers
# -------------------------

def maybe_choose_encoding(owner,
                          suggest_encoding: str,
                          suggest_bom: bool,
                          title: str,
                          body: str) -> tuple[str, str, bool] | None:
    """
    Simple 2-step chooser:
      1) Ask to keep the current encoding/BOM.
      2) If not, prompt for another encoding string and BOM toggle.
    Returns (encoding, errors, add_bom) or None if cancelled.
    """
    enc_label = suggest_encoding or "utf-8"
    bom_label = " +BOM" if suggest_bom else ""
    use_suggest = messagebox.askyesno(title, f"{body}\n\nUse {enc_label}{bom_label}?", parent=owner, default="yes")
    if use_suggest:
        return (enc_label, "strict", suggest_bom)

    # Ask for another encoding
    new_enc = simpledialog.askstring(title, "Enter encoding (e.g. utf-8, latin-1, cp1252):",
                                     initialvalue=enc_label, parent=owner)
    if not new_enc:
        return None

    new_bom = messagebox.askyesno(title, "Include UTF-8 BOM?", parent=owner, default="no")
    return (_canonical_encoding(new_enc), "strict", new_bom)

# -------------------------
# Open with encoding
# -------------------------

# -------------------------
# Save-As with encoding (existing)
# -------------------------

def prompt_save_as_with_encoding(owner,
                                 suggest_path: Path | None,
                                 suggest_enc: str,
                                 suggest_bom: bool) -> tuple[Path, str, str, bool] | None:
    """
    Standard Save As: choose a filename, then confirm/adjust encoding.
    Returns (path, encoding, errors, add_bom) or None if cancelled.
    """
    fname = filedialog.asksaveasfilename(parent=owner,
                                         initialfile=(suggest_path.name if suggest_path else "untitled.txt"))
    if not fname:
        return None

    enc_choice = maybe_choose_encoding(
        owner, suggest_enc or "utf-8", suggest_bom,
        "Save As", f"Save to:\n{fname}\n\nSelect encoding."
    )
    if not enc_choice:
        return None
    enc, errors, add_bom = enc_choice
    return (Path(fname), enc, errors, add_bom)

import tkinter as tk
from tkinter import ttk

import tkinter as tk
from tkinter import ttk

# --- Encoding helpers with BOM folded into the "encoding name" ----------------
# Accept canonical names like "utf-8", plus BOM-flavored names like "utf-8-with-bom".
# Callers no longer pass a separate add_bom flag. We treat BOM as part of the encoding.

def _normalize_encoding_name(name: str) -> tuple[str, bool]:
    """
    Returns (base_encoding, add_bom) after interpreting BOM as part of the encoding name.
    Examples:
      "utf-8"           -> ("utf-8", False)
      "utf-8-with-bom"  -> ("utf-8", True)
      "utf-16-le"       -> ("utf-16-le", False)   # (BOM handling not auto-added here)
    """
    s = (name or "").strip().lower().replace("_", "-")
    if s in ("utf-8-sig", "utf8-sig", "utf-8-with-bom", "utf8-with-bom"):
        return ("utf-8", True)
    return (s, False)

import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

# ---------- binary I/O ----------
def read_text_bytes(path: Path) -> bytes:
    return Path(path).read_bytes()

def save_to_path(path: Path, data: bytes) -> None:
    Path(path).write_bytes(data)

# ---------- decoding ----------
def suggest_open_encoding(path: Path) -> str:
    """
    Very light suggestion: prefer UTF-8; if file starts with UTF-8 BOM, use utf-8-with-bom
    (we treat BOM as part of the encoding name).
    Extend this as needed (uchardet/chardet etc.) — keeping logic here per spec.
    """
    b = read_text_bytes(path)[:4]
    if b.startswith(b"\xef\xbb\xbf"):
        return "utf-8-with-bom"
    return "utf-8"

def decode_bytes(b: bytes, encoding: str, errors: str = "strict") -> str:
    if encoding.lower() == "utf-8-with-bom":
        # Python codec 'utf-8-sig' strips BOM on decode
        return b.decode("utf-8-sig", errors=errors)
    return b.decode(encoding, errors=errors)

# ---------- encoding ----------
def encode_text(text: str, encoding: str) -> bytes:
    """
    Encode text respecting 'utf-8-with-bom' as a bona fide encoding label.
    """
    enc = encoding.lower()
    if enc == "utf-8-with-bom":
        raw = text.encode("utf-8")
        return b"\xef\xbb\xbf" + raw
    return text.encode(encoding)

import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

# … keep your other functions (read_text_bytes, save_to_path, suggest_open_encoding, decode_bytes, encode_text) …

# Shared encoding list (ASCII removed)
_DEF_ENCODINGS = [
    "utf-8",
    "utf-8-with-bom",
    "utf-16-le",
    "utf-16-be",
    "latin-1",
    "windows-1252",
]

def _apply_dark_combo_style(owner, stylename="ZP.TCombobox"):
    """Dark-theme a ttk.Combobox field (note: native dropdown list may still follow system)."""
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


# ---------- unified “inline” encoding picker for Save Over ----------
def encode_text_inline(owner, text: str, default_encoding: str):
    """
    One modal that’s wide enough; returns (data: bytes, final_encoding: str).
    BOM is expressed as 'utf-8-with-bom' in the encoding list (no checkbox).
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
    enc_var = tk.StringVar(value=default_encoding or "utf-8")
    enc_box = ttk.Combobox(frm, textvariable=enc_var, values=ENCODINGS, state="readonly",
                           width=28, style="ZP.TCombobox")
    enc_box.grid(row=0, column=1, sticky="w", padx=(8, 0))

    # Buttons
    btns = tk.Frame(frm, bg=bg)
    btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(14, 0))
    out = {"res": None}

    from tkinter import messagebox

    def ok():
        enc = enc_var.get().strip() or (default_encoding or "utf-8")
        try:
            data = encode_text(text, enc)
        except Exception as e:
            messagebox.showerror("Encoding Error", f"Could not encode text:\n{e}")
            return
        out["res"] = (data, enc)
        win.destroy()

    def cancel():
        out["res"] = None
        win.destroy()

    ttk.Button(btns, text="OK", command=ok).pack(side="right")
    ttk.Button(btns, text="Cancel", command=cancel).pack(side="right", padx=(0, 8))

    # Nice sizing/placement
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

    if not out["res"]:
        raise RuntimeError("Canceled")
    return out["res"]


# ---------- Save As (single dialog with encoding) ----------
def prompt_save_as_with_encoding(owner, suggest_path: Path | None, suggest_enc: str):
    """
    Built-in save-as with encoding selector in the same dialog.
    Returns (path: Path, encoding: str) or None.
    """
    ENCODINGS = list(_DEF_ENCODINGS)

    pal = getattr(owner, "_palette", {})
    bg = pal.get("BG_PANEL", "#111827")
    fg = pal.get("FG_TEXT",  "#e5e7eb")

    win = tk.Toplevel(owner)
    win.withdraw()
    win.title("Save As")
    win.configure(bg=bg)
    win.transient(owner)
    win.grab_set()

    frm = tk.Frame(win, bg=bg)
    frm.pack(fill="both", expand=True, padx=16, pady=16)

    # path row
    tk.Label(frm, text="File:", bg=bg, fg=fg).grid(row=0, column=0, sticky="w")
    path_var = tk.StringVar(value=(str(suggest_path) if suggest_path else ""))
    entry = tk.Entry(frm, textvariable=path_var, bg="#0b1220", fg=fg, insertbackground=fg, relief="flat", width=48)
    entry.grid(row=0, column=1, sticky="we", padx=(8, 0))
    frm.grid_columnconfigure(1, weight=1)

    def browse():
        initfile = suggest_path.name if suggest_path else "untitled.txt"
        fname = filedialog.asksaveasfilename(parent=owner, initialfile=initfile)
        if fname:
            path_var.set(fname)

    ttk.Button(frm, text="Browse…", command=browse).grid(row=0, column=2, sticky="w", padx=(8, 0))

    # encoding row
    tk.Label(frm, text="Encoding:", bg=bg, fg=fg).grid(row=1, column=0, sticky="w", pady=(10,0))
    _apply_dark_combo_style(owner)
    enc_var = tk.StringVar(value=(suggest_enc or "utf-8"))
    enc_box = ttk.Combobox(frm, textvariable=enc_var, values=ENCODINGS, state="readonly",
                           width=28, style="ZP.TCombobox")
    enc_box.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(10,0))

    # buttons
    btns = tk.Frame(frm, bg=bg)
    btns.grid(row=2, column=0, columnspan=3, sticky="e", pady=(14, 0))
    out = {"res": None}

    from tkinter import messagebox

    def ok():
        p = path_var.get().strip()
        if not p:
            messagebox.showerror("Save As", "Please choose a file path.")
            return
        enc = enc_var.get().strip() or "utf-8"
        out["res"] = (Path(p), enc)
        win.destroy()

    def cancel():
        out["res"] = None
        win.destroy()

    ttk.Button(btns, text="OK", command=ok).pack(side="right")
    ttk.Button(btns, text="Cancel", command=cancel).pack(side="right", padx=(0, 8))

    # sizing
    win.update_idletasks()
    try:
        px, py = owner.winfo_rootx(), owner.winfo_rooty()
        pw, ph = owner.winfo_height(), owner.winfo_height()
    except Exception:
        px = py = 0
        pw = ph = 800
    ww, wh = 600, 200
    try:
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


# ---------- Integrated “Open Selected” chooser (system vs Zeropad+encoding) ----------
def choose_open_selected(owner, path: Path):
    """
    Ask how to open the selected file:
      - Cancel → returns None
      - Open with System Default → returns "system"
      - Open in Zeropad → returns "zeropad"

    Uses a safe, deferred grab to avoid 'grab failed' and shutdown races.
    """
    import tkinter as tk
    from tkinter import ttk

    # Palette (dark)
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

    # Content
    tk.Label(win, text="Open selected file with:", bg=BG, fg=FG, anchor="w").pack(
        side="top", fill="x", padx=14, pady=(14, 6)
    )
    tk.Label(win, text=str(path), bg=BG, fg=FG, anchor="w", justify="left", wraplength=640).pack(
        side="top", fill="x", padx=14, pady=(0, 10)
    )

    btns = tk.Frame(win, bg=BG)
    btns.pack(side="top", fill="x", padx=14, pady=(0, 14))

    choice = {"val": None}

    def on_cancel():
        choice["val"] = None
        _close()

    def on_system():
        choice["val"] = "system"
        _close()

    def on_zeropad():
        choice["val"] = "zeropad"
        _close()

    def _close():
        # Release grab if we own it, then destroy
        if win.winfo_exists():
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

    ttk.Button(btns, text="Cancel", style="Dlg.TButton", command=on_cancel).pack(side="right")
    ttk.Button(btns, text="Open in Zeropad", style="Dlg.TButton", command=on_zeropad).pack(side="right", padx=(0, 8))
    ttk.Button(btns, text="Open with System Default", style="Dlg.TButton", command=on_system).pack(side="right", padx=(0, 8))

    win.bind("<Escape>", lambda e: on_cancel())
    win.protocol("WM_DELETE_WINDOW", on_cancel)

    # Center relative to owner, then show
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

    # Safe, deferred grab loop to avoid "grab failed" and shutdown races.
    # If the window is destroyed (e.g., app exit), we simply stop retrying.
    def _try_grab():
        if not win.winfo_exists():
            return
        # Only grab once it’s viewable
        if not win.winfo_viewable():
            win.after(15, _try_grab)
            return
        try:
            win.grab_set()
        except tk.TclError:
            # Retry shortly; some WMs need a second tick
            win.after(15, _try_grab)

    win.after(0, _try_grab)
    try:
        win.wait_window()
    except tk.TclError:
        # If the app is closing, the window may be gone already
        return None

    return choice["val"]
