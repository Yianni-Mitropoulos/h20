"""
FILE PANEL (Zeropad)

COLUMN WIDTH MODEL — READ THIS BEFORE EDITING:

We use a FIXED-WIDTH model for columns with a single FLEX column for the filename.

- Each non-filename column has a persistent desired pixel width stored in `self._col_target_px[col]`.
- Each column also has a min and a max width (`_col_min_px`, `_col_max_px_base` plus dynamic caps).
- Exactly ONE column is the “flex” (expanding) column:
    • If Type is ON  → 'name' is the filename column and is the flex column.
    • If Type is OFF → '#0' shows the filename and becomes the flex column.
- Layout:
    1) Clamp each FIXED (non-filename) column to [min..max] and sum them.
    2) Flex column width = remaining pixels, clamped to its min (no max; it can grow indefinitely).
- When the user drags a separator, we update ONLY that fixed column’s target width. The flex column is
  recomputed automatically.

EXTENSION → MIME OVERRIDES:

We load a pragmatic mapping from a file named `extensions.txt` (optional). Format:

    # comments and blank lines allowed
    .py   text/x-python
    py    text/x-python
    .mjs  application/javascript
    jsx = text/javascript

Separator can be whitespace or '='. Leading '.' on extension is optional.

Overrides are preferred over GIO content guessing (fixes empty .py → text/x-python).
"""

import os
import stat
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, List

# ---- safety utils (project file) ----
from string_safety_utils import (
    bad_filename_check,
    bad_filename_sanitize,
    deceptive_line_check,
    deceptive_line_sanitize,
)

# ---- Optional GIO + GdkPixbuf (no GTK) ----
try:
    import gi
    gi.require_version("Gio", "2.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gio, GdkPixbuf
    _HAS_GIO = True
    _HAS_GDKPB = True
except Exception:
    Gio = None            # type: ignore
    GdkPixbuf = None      # type: ignore
    _HAS_GIO = False
    _HAS_GDKPB = False

class FilePanel:
    # ---------------- init & UI ----------------

    def init_file_panel(self):
        """Build the left File panel with three vertically stacked subpanels."""
        palette = getattr(self, "_palette", {})
        self._BG_PANEL = palette.get("BG_PANEL", "#111827")
        self._FG_TEXT  = palette.get("FG_TEXT",  "#e5e7eb")
        self._BG_ENTRY = "#0b1220"
        self._FG_DIM   = "#9ca3af"
        self._BTN_BG   = "#1f2937"
        self._BTN_BG_H = "#374151"
        self._BTN_BG_D = "#111827"
        self._ACC_BG   = "#2563eb"
        self._ACC_BG_H = "#3b82f6"
        self._ACC_BG_D = "#0b1220"
        self._ERR_RED  = "#ef4444"

        # Load ext overrides from extensions.txt (if present)
        self._ext_overrides = self._load_ext_overrides()

        # Root frame for the file panel
        self.fm = tk.Frame(self.hpaned, bg=self._BG_PANEL)

        # ---------- Styles ----------
        style = ttk.Style(self)
        style.configure("NoHover.TCheckbutton", background=self._BG_PANEL, foreground=self._FG_TEXT)
        style.map("NoHover.TCheckbutton",
                  background=[("active", self._BG_PANEL), ("!disabled", self._BG_PANEL)],
                  foreground=[("active", self._FG_TEXT), ("!disabled", self._FG_TEXT)])

        style.configure("Toolbar.TButton", background=self._BTN_BG, foreground=self._FG_TEXT,
                        borderwidth=0, padding=(8, 2))
        style.map("Toolbar.TButton",
                  background=[("active", self._BTN_BG_H), ("disabled", self._BTN_BG_D)],
                  foreground=[("disabled", self._FG_DIM)])

        style.configure("Primary.TButton", background=self._ACC_BG, foreground="#ffffff",
                        borderwidth=0, padding=(10, 4))
        style.map("Primary.TButton",
                  background=[("active", self._ACC_BG_H), ("disabled", self._ACC_BG_D)],
                  foreground=[("disabled", self._FG_DIM)])
        style.configure("Secondary.TButton", background=self._BTN_BG, foreground=self._FG_TEXT,
                        borderwidth=0, padding=(10, 4))
        style.map("Secondary.TButton",
                  background=[("active", self._BTN_BG_H)],
                  foreground=[("disabled", self._FG_DIM)])

        style.configure("Treeview",
                        background=self._BG_PANEL, fieldbackground=self._BG_PANEL,
                        foreground=self._FG_TEXT, borderwidth=0)
        style.configure("Treeview.Heading",
                        background=self._BTN_BG, foreground=self._FG_TEXT, relief="flat")
        style.map("Treeview.Heading",
                  background=[("active", self._BTN_BG_H), ("pressed", self._BTN_BG_H)],
                  foreground=[("active", self._FG_TEXT), ("pressed", self._FG_TEXT)])

        # ---------- Subpanel 1: toggles + nav ----------
        topbar = tk.Frame(self.fm, bg=self._BG_PANEL)
        topbar.pack(side="top", fill="x")

        self.show_hidden = tk.BooleanVar(value=False)
        ttk.Checkbutton(topbar, text="Show Hiddens", variable=self.show_hidden,
                        command=self._on_show_hidden, style="NoHover.TCheckbutton",
                        takefocus=False).pack(side="left", padx=(8, 6), pady=6)

        # Use MIME types (auto-on if libs present)
        self.use_mime_types = tk.BooleanVar(value=(_HAS_GIO and _HAS_GDKPB))
        ttk.Checkbutton(topbar, text="Use MIME Types", variable=self.use_mime_types,
                        command=self._on_toggle_mime, style="NoHover.TCheckbutton",
                        takefocus=False).pack(side="left", padx=(0, 12), pady=6)

        self.up_btn = ttk.Button(topbar, text="Up", style="Toolbar.TButton", command=self._go_up)
        self.up_btn.pack(side="left", padx=(0, 6), pady=6)

        self.home_btn = ttk.Button(topbar, text="Home", style="Toolbar.TButton",
                                   command=lambda: self.set_cwd(Path.home()))
        self.home_btn.pack(side="left", padx=(0, 8), pady=6)

        # ---------- Subpanel 2: Tree ----------
        middle = tk.Frame(self.fm, bg=self._BG_PANEL)
        middle.pack(side="top", fill="both", expand=True)
        self.tree = ttk.Treeview(middle, show="tree headings", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)

        # Bold font for "Create New" rows
        base = tkfont.nametofont("TkDefaultFont")
        self._bold_font = tkfont.Font(self, family=base.cget("family"),
                                      size=base.cget("size"), weight="bold")
        self.tree.tag_configure("bold", font=self._bold_font)

        # --- Width model: desired pixel widths (only filename flexes) ---
        self._col_target_px: Dict[str, int] = {
            "#0":       120,  # kind text OR filename (when Type OFF). Capped to 40px in icon mode.
            "name":     260,  # filename (when Type ON) — this FLEXes
            "safe":      28,  # '!' column — narrow, centered
            "size":     110,
            "modified": 180,
            "mode":      90,
        }
        self._col_min_px: Dict[str, int] = {
            "#0": 56, "name": 120, "safe": 28, "size": 80, "modified": 140, "mode": 70
        }
        self._col_max_px_base: Dict[str, int] = {
            "#0": 240, "name": 10_000, "safe": 28, "size": 220, "modified": 280, "mode": 120
        }

        self._resizing_col = False
        self._resized_col: Optional[str] = None
        self.tree.bind("<ButtonPress-1>", self._on_tree_press, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release, add="+")
        self.tree.bind("<Configure>", lambda _e: self._apply_fixed_widths())

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # Map item_id -> dict(path=Path, kind='dir'|'file'|'create_dir'|'create_file', role='...')
        self._node: Dict[str, Dict] = {}

        # Sorting state
        self._sort_key = "#0"   # start on Type column
        self._sort_desc = False
        self._last_cwd: Path | None = None

        # MIME cache (path -> (mime, icon_name))
        self._mime_cache: Dict[Path, Tuple[Optional[str], Optional[str]]] = {}

        # ---------- Subpanel 3: Metadata + visibility ----------
        bottom = tk.Frame(self.fm, bg=self._BG_PANEL)
        bottom.pack(side="top", fill="x")

        form = tk.Frame(bottom, bg=self._BG_PANEL, highlightthickness=0, bd=0)
        form.pack(side="top", fill="x", padx=8, pady=(8, 6))
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(2, minsize=24)

        # Column visibility toggles
        self.col_type     = tk.BooleanVar(value=True)   # unified Type
        self.col_name     = tk.BooleanVar(value=True)   # Filename column (shown only when Type ON)
        self.col_size     = tk.BooleanVar(value=True)
        self.col_modified = tk.BooleanVar(value=False)
        self.col_mode     = tk.BooleanVar(value=False)

        # Row 0: Type (unified)
        self._row0_left  = tk.Frame(form, bg=self._BG_PANEL)
        self._row0_value = tk.Frame(form, bg=self._BG_PANEL)
        self._row0_left.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._row0_value.grid(row=0, column=1, sticky="ew", pady=2)
        self._update_row0_mode_ui()  # builds controls depending on MIME availability

        # Row 1: Filename (label disabled + entry + safety glyph)
        fn_label_wrap = tk.Frame(form, bg=self._BG_PANEL)
        fn_label_wrap.grid(row=1, column=0, sticky="w", padx=(0, 6))
        ttk.Checkbutton(fn_label_wrap, variable=self.col_name, text="Filename",
                        style="NoHover.TCheckbutton", takefocus=False, state="disabled").pack(anchor="w")

        self.meta_filename = tk.Entry(form, bg=self._BG_ENTRY, fg=self._FG_TEXT,
                                      insertbackground=self._FG_TEXT, relief="flat")
        self.meta_filename.grid(row=1, column=1, sticky="ew", pady=2)

        self.meta_fname_flag = tk.Label(form, text="🙂", bg=self._BG_PANEL, fg=self._FG_TEXT, cursor="hand2")
        self.meta_fname_flag.grid(row=1, column=2, sticky="e", padx=(6, 0))
        self.meta_fname_flag.bind("<Button-1>", lambda _e: self._on_meta_flag_clicked())

        # Row 2: Size
        ttk.Checkbutton(form, variable=self.col_size, text="Size",
                        command=self._apply_tree_columns,
                        style="NoHover.TCheckbutton", takefocus=False)\
            .grid(row=2, column=0, sticky="w", padx=(0, 6))
        self.meta_size = tk.Label(form, anchor="w", bg=self._BG_PANEL, fg=self._FG_TEXT)
        self.meta_size.grid(row=2, column=1, sticky="ew", pady=2)

        # Row 3: Modified
        ttk.Checkbutton(form, variable=self.col_modified, text="Modified",
                        command=self._apply_tree_columns,
                        style="NoHover.TCheckbutton", takefocus=False)\
            .grid(row=3, column=0, sticky="w", padx=(0, 6))
        self.meta_modified = tk.Entry(form, bg=self._BG_ENTRY, fg=self._FG_TEXT,
                                      insertbackground=self._FG_TEXT, relief="flat")
        self.meta_modified.grid(row=3, column=1, sticky="ew", pady=2)

        # Row 4: Mode
        ttk.Checkbutton(form, variable=self.col_mode, text="Mode",
                        command=self._apply_tree_columns,
                        style="NoHover.TCheckbutton", takefocus=False)\
            .grid(row=4, column=0, sticky="w", padx=(0, 6))
        self.meta_mode = tk.Entry(form, bg=self._BG_ENTRY, fg=self._FG_TEXT,
                                  insertbackground=self._FG_TEXT, relief="flat")
        self.meta_mode.grid(row=4, column=1, sticky="ew", pady=2)

        # Buttons (Delete | Cancel | Accept)
        btns = tk.Frame(bottom, bg=self._BG_PANEL)
        btns.pack(side="top", fill="x", padx=8, pady=(0, 8))
        self.accept_btn = ttk.Button(btns, text="Accept", command=self._on_accept, style="Primary.TButton")
        self.cancel_btn = ttk.Button(btns, text="Cancel", command=self._on_cancel, style="Secondary.TButton")
        self.delete_btn = ttk.Button(btns, text="Delete", command=self._on_delete, style="Secondary.TButton")
        self.accept_btn.pack(side="right")
        self.cancel_btn.pack(side="right", padx=(0, 8))
        self.delete_btn.pack(side="left")
        self._set_accept_enabled(False)

        # Selection tracking
        self._selected_path: Path | None = None
        self._meta_original = {"filename": "", "modified": "", "mode": ""}
        self._create_mode: str | None = None  # None | "dir" | "file"

        # Live-edit dirty tracking and safety glyph updates
        for w in (self.meta_filename, self.meta_modified, self.meta_mode):
            w.bind("<KeyRelease>", self._on_meta_edited)

        # Image cache for icons
        self._img_cache: dict[str, tk.PhotoImage] = {}

        # Build columns & rows
        self._apply_tree_columns()

    # ---------------- MIME toggle & Row0 ----------------

    def _mime_enabled(self) -> bool:
        return bool(self.use_mime_types.get() and _HAS_GIO and _HAS_GDKPB)

    def _on_toggle_mime(self):
        if self.use_mime_types.get():
            if not (_HAS_GIO and _HAS_GDKPB):
                messagebox.showwarning(
                    "MIME Support Unavailable",
                    "GIO/GdkPixbuf not found.\n\nInstall on Debian/Ubuntu:\n"
                    "  sudo apt install python3-gi gir1.2-gio-2.0 gir1.2-gdkpixbuf-2.0\n"
                    "  sudo apt install librsvg2-common shared-mime-info hicolor-icon-theme\n"
                    "  # (optional) xdg-utils\n"
                )
                self.use_mime_types.set(False)
                return
        self._mime_cache.clear()
        self._update_row0_mode_ui()
        self._apply_tree_columns()

    def _update_row0_mode_ui(self):
        for w in self._row0_left.winfo_children():
            w.destroy()
        for w in self._row0_value.winfo_children():
            w.destroy()

        ttk.Checkbutton(self._row0_left, variable=self.col_type, text="Type",
                        command=self._apply_tree_columns,
                        style="NoHover.TCheckbutton", takefocus=False).pack(anchor="w")

        if self._mime_enabled():
            self.meta_icon_img = tk.Label(self._row0_value, bg=self._BG_PANEL)
            self.meta_icon_img.pack(side="left", padx=(0, 8))
            self.meta_mime_text = tk.Label(self._row0_value, anchor="w", bg=self._BG_PANEL, fg=self._FG_TEXT)
            self.meta_mime_text.pack(side="left", fill="x", expand=True)
        else:
            self.meta_kind_value = tk.Label(self._row0_value, anchor="w", bg=self._BG_PANEL, fg=self._FG_TEXT)
            self.meta_kind_value.pack(side="left", fill="x", expand=True)

    # ---------------- Safety helpers ----------------

    def _filename_issues(self, name: str):
        issues = []
        for _i, msg in deceptive_line_check(name, low_aggression=False):
            issues.append(msg)
        for _i, msg in bad_filename_check(name):
            issues.append(msg)
        return issues

    def _is_name_safe(self, name: str) -> bool:
        return (name is None) or (name == "") or (len(self._filename_issues(name)) == 0)

    def _tree_safety_icon(self, name: str) -> str:
        return "" if self._is_name_safe(name) else "☹"

    def _meta_safety_icon(self, name: str) -> str:
        return "🙂" if self._is_name_safe(name) else "☹"

    # ---------------- Column model ----------------

    def _visible_cols(self) -> List[str]:
        """
        Visible columns in UI order.
        • Type ON  : '#0' (icon/kind), 'name', 'safe', ...
        • Type OFF : '#0' (filename), 'safe', ...
        """
        cols = ["#0"]
        if self.col_type.get():
            cols += ["name", "safe"]
        else:
            cols += ["safe"]
        if self.col_size.get():     cols.append("size")
        if self.col_modified.get(): cols.append("modified")
        if self.col_mode.get():     cols.append("mode")
        return cols

    def _tree_columns(self):
        cols, heads = [], {}
        if self.col_type.get():
            cols += ["name", "safe"]; heads["name"] = "Filename"; heads["safe"] = "!"
        else:
            cols += ["safe"];         heads["safe"] = "!"
        if self.col_size.get():     cols.append("size");     heads["size"] = "Size"
        if self.col_modified.get(): cols.append("modified"); heads["modified"] = "Modified"
        if self.col_mode.get():     cols.append("mode");     heads["mode"] = "Mode"
        return cols, heads

    def _apply_tree_columns(self):
        cols, heads = self._tree_columns()
        self.tree.configure(columns=cols)

        # #0 heading (empty label for icon column, triangles still shown)
        self.tree.heading("#0", text=self._sort_label_for("#0"), anchor="center",
                          command=lambda: self._on_heading_click("#0"))
        for c in ("name", "safe", "size", "modified", "mode"):
            if c not in cols:
                continue
            if c == "safe":
                self.tree.heading(c, text=heads.get(c, "!"), anchor="center")
                continue
            self.tree.heading(c, text=self._sort_label_for(c), command=lambda col=c: self._on_heading_click(col))

        self._apply_fixed_widths()
        self.refresh_file_panel()

    def _filename_flex_col(self) -> str:
        return "name" if self.col_type.get() else "#0"

    def _dynamic_max_caps(self) -> Dict[str, int]:
        caps = dict(self._col_max_px_base)
        if self.col_type.get() and self._mime_enabled():
            caps["#0"] = 40  # icon column
        else:
            if not self.col_type.get():
                caps["#0"] = 10_000  # #0 is filename → allow growth
        caps[self._filename_flex_col()] = 10_000_000  # filename flex column
        return caps

    def _apply_fixed_widths(self):
        vis = self._visible_cols()
        if not vis:
            return
        tree_w = max(self.tree.winfo_width(), 1)
        if tree_w <= 2:
            self.tree.after(16, self._apply_fixed_widths)
            return

        caps = self._dynamic_max_caps()
        flex = self._filename_flex_col()

        fixed_sum = 0
        col_widths: Dict[str, int] = {}
        for c in vis:
            if c == flex:
                continue
            tgt = self._col_target_px.get(c, self._col_min_px.get(c, 50))
            w = max(self._col_min_px.get(c, 50), min(caps.get(c, 10_000), int(tgt)))
            col_widths[c] = w
            fixed_sum += w

        remain = tree_w - fixed_sum
        flex_min = self._col_min_px.get(flex, 80)
        flex_w = max(flex_min, remain)
        col_widths[flex] = flex_w

        for c in vis:
            if c == "#0":
                anchor = "center" if (self.col_type.get() and self._mime_enabled()) else "w"
            elif c == "safe":
                anchor = "center"
            else:
                anchor = "w"
            self.tree.column(c, width=max(1, col_widths[c]), stretch=True, anchor=anchor)

        # Park hidden data columns
        for c in ("name", "safe", "size", "modified", "mode"):
            if c not in self.tree["columns"]:
                continue
            if c not in vis:
                self.tree.column(c, width=self._col_min_px.get(c, 50), stretch=False, anchor="w")

    # --- capture user resize to update fixed target widths
    def _on_tree_press(self, event):
        self._resizing_col = (self.tree.identify_region(event.x, event.y) == "separator")
        self._resized_col = None
        if self._resizing_col:
            col_id = self.tree.identify_column(event.x)  # '#0', '#1', ...
            vis = self._visible_cols()
            if col_id == "#0":
                self._resized_col = "#0"
            else:
                try:
                    idx = int(col_id.replace("#", "")) - 1
                    if 0 <= idx < len(self.tree["columns"]):
                        self._resized_col = self.tree["columns"][idx]
                except Exception:
                    self._resized_col = None

    def _on_tree_release(self, _event):
        if self._resizing_col:
            vis = self._visible_cols()
            flex = self._filename_flex_col()
            if self._resized_col in vis and self._resized_col != flex:
                try:
                    cur = int(self.tree.column(self._resized_col, option="width"))
                    caps = self._dynamic_max_caps()
                    cur = max(self._col_min_px.get(self._resized_col, 50),
                              min(caps.get(self._resized_col, 10_000), cur))
                    self._col_target_px[self._resized_col] = cur
                except Exception:
                    pass
            self._apply_fixed_widths()
        self._resizing_col = False
        self._resized_col = None

    # ---------------- Sorting ----------------

    def _on_show_hidden(self):
        self.refresh_file_panel()

    def _effective_sort_attr(self, col: str) -> str:
        if col == "#0":
            if not self.col_type.get():
                return "name"  # Type OFF → #0 is filename (sort by filename)
            return "mime" if self._mime_enabled() else "kind"
        return col

    def _sort_label_for(self, col: str) -> str:
        if col == "#0":
            base = "" if (self.col_type.get() and self._mime_enabled()) else ("Kind" if self.col_type.get() else "Filename")
        else:
            base = "Filename" if col == "name" else ("!" if col == "safe" else col.capitalize())
        if col == self._sort_key and col != "safe":
            return f"{base} {'▼' if not self._sort_desc else '▲'}".strip()
        return base

    def _key_for_entry(self, p: Path, key: str):
        """
        Stable, minimal keys:
        - Directories before files (0/1).
        - Then the requested attribute.
        - IMPORTANT: No fallback to name here (unless key == 'name'). Ties remain in prior order.
        """
        is_dir = 0 if p.is_dir() else 1
        try:
            if key == "name":
                return (is_dir, p.name.lower())
            if key == "kind":
                # group dirs vs files, no further tiebreaker
                return (is_dir, 0)  # same value within group → stable by prior order
            if key == "mime":
                if p.is_dir():
                    return (0, 0)  # dirs grouped; equal → stable
                mime, _ = self._guess_mime_for(p)
                mime = (mime or "application/octet-stream").lower()
                return (1, mime)
            if key == "size":
                st = p.stat()
                return (is_dir, -1 if p.is_dir() else st.st_size)
            if key == "modified":
                st = p.stat()
                return (is_dir, st.st_mtime)
            if key == "mode":
                st = p.stat()
                return (is_dir, stat.S_IMODE(st.st_mode))
        except Exception:
            return (is_dir, 0)
        return (is_dir, 0)

    def _stably_sort_entries(self, entries: List[Path]):
        key_attr = self._effective_sort_attr(self._sort_key)
        reverse = self._sort_desc
        return sorted(entries, key=lambda p: self._key_for_entry(p, key_attr), reverse=reverse)

    def _current_order_ranks(self):
        rank_dirs, rank_files = {}, {}
        if not self._node:
            return rank_dirs, rank_files
        idx_dir = idx_file = 0
        for iid in self.tree.get_children(""):
            meta = self._node.get(iid)
            if not meta:
                continue
            role = meta.get("role")
            p = meta.get("path")
            if role == "cwd-dir" and p:
                rank_dirs[Path(p).resolve()] = idx_dir; idx_dir += 1
            elif role == "cwd-file" and p:
                rank_files[Path(p).resolve()] = idx_file; idx_file += 1
        return rank_dirs, rank_files

    def _on_heading_click(self, col: str):
        if col == self._sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key = col
            self._sort_desc = False
        self._apply_tree_columns()
        self.refresh_file_panel()

    # ---------------- Rendering ----------------

    def refresh_file_panel(self):
        cols, heads = self._tree_columns()
        self.tree.configure(columns=cols)

        self.tree.heading("#0", text=self._sort_label_for("#0"), anchor="center",
                          command=lambda: self._on_heading_click("#0"))
        for c in ("name", "safe", "size", "modified", "mode"):
            if c in cols:
                if c == "safe":
                    self.tree.heading(c, text=heads.get(c, "!"), anchor="center")
                else:
                    self.tree.heading(c, text=self._sort_label_for(c),
                                      command=lambda col=c: self._on_heading_click(col))

        self._apply_fixed_widths()

        cwd_changed = (self._last_cwd is None) or (self.cwd != self._last_cwd)
        self._last_cwd = self.cwd

        selected_before = self._selected_path
        rank_dirs, rank_files = self._current_order_ranks()

        self.tree.delete(*self.tree.get_children())
        self._node.clear()

        def _ins(row_text, row_vals, img=None, tags=()):
            kwargs = {"parent": "", "index": "end", "text": row_text, "values": row_vals}
            if img is not None:
                kwargs["image"] = img
            if tags:
                kwargs["tags"] = tags
            return self.tree.insert(**kwargs)

        def icon_for(p: Optional[Path], fallback: str) -> Optional[tk.PhotoImage]:
            if p is None:
                icon_name = fallback
            else:
                _mime, icon_name = self._guess_mime_for(p)
                icon_name = icon_name or fallback
            return self._load_icon_image(icon_name, size=16)

        type_is_icon = self.col_type.get() and self._mime_enabled()

        # Breadcrumbs
        for path, name in self._breadcrumb_items():
            meta = self._values_for_path(path)
            safe = self._tree_safety_icon(name)
            img = icon_for(path, "inode-directory") if type_is_icon else None

            if self.col_type.get():
                if type_is_icon:
                    row_text = ""
                    row_vals = [(name if dc == "name" else (safe if dc == "safe" else meta.get(dc, "")))
                                for dc in cols]
                    iid = _ins(row_text, row_vals, img=img)
                else:
                    row_text = meta.get("#0", "Folder")
                    row_vals = [(name if dc == "name" else (safe if dc == "safe" else meta.get(dc, "")))
                                for dc in cols]
                    iid = _ins(row_text, row_vals)
            else:
                row_text = name
                row_vals = [(safe if dc == "safe" else meta.get(dc, "")) for dc in cols]
                iid = _ins(row_text, row_vals)
            self._node[iid] = {"path": path, "kind": "dir", "role": "breadcrumb"}

        # Create New Folder
        img_new_folder = icon_for(None, "folder-new") if type_is_icon else None
        sep1_vals = [("=== Create New Folder ===" if dc == "name" else "") for dc in cols]
        sep1_text = "" if self.col_type.get() else "=== Create New Folder ==="
        sep1 = _ins(sep1_text, sep1_vals, img=(img_new_folder if type_is_icon else None), tags=("bold",))
        self._node[sep1] = {"path": None, "kind": "create_dir"}

        # Gather entries
        try:
            entries = list(self.cwd.iterdir())
        except Exception:
            entries = []
        show_hidden = self.show_hidden.get()
        dirs  = [e for e in entries if e.is_dir() and (show_hidden or not e.name.startswith("."))]
        files = [e for e in entries if e.is_file() and (show_hidden or not e.name.startswith("."))]

        # Initial name sort on directory change; otherwise preserve current order ranks
        if cwd_changed:
            dirs  = sorted(dirs,  key=lambda p: p.name.lower())
            files = sorted(files, key=lambda p: p.name.lower())
        else:
            dirs  = sorted(dirs,  key=lambda p: rank_dirs.get(p.resolve(), 10**9))
            files = sorted(files, key=lambda p: rank_files.get(p.resolve(), 10**9))

        # Apply current sort (stable; ties keep prior order)
        dirs  = self._stably_sort_entries(dirs)
        files = self._stably_sort_entries(files)

        # Insert dirs
        for d in dirs:
            meta = self._values_for_path(d)
            safe = self._tree_safety_icon(d.name)
            if self.col_type.get():
                if type_is_icon:
                    img = icon_for(d, "inode-directory")
                    row_text = ""
                    row_vals = [(d.name if dc == "name" else (safe if dc == "safe" else meta.get(dc, "")))
                                for dc in cols]
                    iid = _ins(row_text, row_vals, img=img)
                else:
                    row_text = meta.get("#0", "Folder")
                    row_vals = [(d.name if dc == "name" else (safe if dc == "safe" else meta.get(dc, "")))
                                for dc in cols]
                    iid = _ins(row_text, row_vals)
            else:
                row_text = d.name
                row_vals = [(safe if dc == "safe" else meta.get(dc, "")) for dc in cols]
                iid = _ins(row_text, row_vals)
            self._node[iid] = {"path": d, "kind": "dir", "role": "cwd-dir"}

        # Create New File
        img_new_file = icon_for(None, "document-new") if type_is_icon else None
        sep2_vals = [("=== Create New File ===" if dc == "name" else "") for dc in cols]
        sep2_text = "" if self.col_type.get() else "=== Create New File ==="
        sep2 = _ins(sep2_text, sep2_vals, img=(img_new_file if type_is_icon else None), tags=("bold",))
        self._node[sep2] = {"path": None, "kind": "create_file"}

        # Insert files
        for f in files:
            meta = self._values_for_path(f)
            safe = self._tree_safety_icon(f.name)
            if self.col_type.get():
                if type_is_icon:
                    _mime, icon_name = self._guess_mime_for(f)
                    img = self._load_icon_image(icon_name or "text-x-generic", size=16)
                    row_text = ""
                    row_vals = [(f.name if dc == "name" else (safe if dc == "safe" else meta.get(dc, "")))
                                for dc in cols]
                    iid = _ins(row_text, row_vals, img=img)
                else:
                    row_text = meta.get("#0", "File")
                    row_vals = [(f.name if dc == "name" else (safe if dc == "safe" else meta.get(dc, "")))
                                for dc in cols]
                    iid = _ins(row_text, row_vals)
            else:
                row_text = f.name
                row_vals = [(safe if dc == "safe" else meta.get(dc, "")) for dc in cols]
                iid = _ins(row_text, row_vals)
            self._node[iid] = {"path": f, "kind": "file", "role": "cwd-file"}

        self._update_nav_buttons()
        if selected_before is not None:
            self._select_path(selected_before)
        self._update_meta_safety_from_entry()

    # ---------------- Selection & metadata ----------------

    def _on_tree_select(self, _evt):
        iid = self._first_selection()
        if not iid:
            return
        info = self._node.get(iid, {})
        kind = info.get("kind")

        if kind == "create_dir":
            self._enter_create_mode("dir"); return
        if kind == "create_file":
            self._enter_create_mode("file"); return

        if kind in ("dir", "file"):
            path = info.get("path")
            if path:
                self._selected_path = path
                self._create_mode = None
                self._load_metadata_from_path(path)

    def _enter_create_mode(self, what: str):
        self._selected_path = None
        self._create_mode = what
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode = "0755" if what == "dir" else "0644"
        kind = "Folder" if what == "dir" else "File"
        size = "-" if what == "dir" else "0 B"

        self.meta_filename.delete(0, tk.END)
        if self._mime_enabled():
            self.meta_icon_img.config(image=""); self.meta_icon_img.image = None
            self.meta_mime_text.config(text="")
        else:
            self.meta_kind_value.config(text=kind)
        self.meta_size.config(text=size)
        self.meta_modified.delete(0, tk.END); self.meta_modified.insert(0, now)
        self.meta_mode.delete(0, tk.END);     self.meta_mode.insert(0, mode)

        self._meta_original = {"filename": "", "modified": now, "mode": mode}
        self._set_accept_enabled(False)
        self._update_meta_safety_from_entry()
        self.meta_filename.focus_set()

    def _on_tree_double_click(self, _evt):
        iid = self._first_selection()
        if not iid:
            return
        info = self._node.get(iid)
        if not info:
            return
        if info.get("kind") == "dir":
            self.set_cwd(info["path"])

    def _first_selection(self):
        sels = self.tree.selection()
        return sels[0] if sels else None

    def _select_path(self, p: Path):
        target = None
        for iid, meta in self._node.items():
            if meta.get("path") and Path(meta["path"]).resolve() == Path(p).resolve():
                target = iid; break
        if target:
            try:
                self.tree.selection_set(target)
                self.tree.focus(target)
                self.tree.see(target)
            except Exception:
                pass

    def _load_metadata_from_path(self, p: Path):
        try:
            st = p.stat()
        except Exception as e:
            messagebox.showerror("Error", f"Unable to stat: {p}\n{e}")
            return

        kind = "Folder" if p.is_dir() else "File"
        size = "-" if p.is_dir() else self._human_size(st.st_size)
        mtime_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        mode_str = f"{stat.S_IMODE(st.st_mode):04o}"

        self.meta_filename.delete(0, tk.END); self.meta_filename.insert(0, p.name)
        if self._mime_enabled():
            mime, icon_name = self._guess_mime_for(p)
            img = self._load_icon_image(icon_name or "", 16)
            if hasattr(self, "meta_icon_img"):
                self.meta_icon_img.config(image=img); self.meta_icon_img.image = img
            if hasattr(self, "meta_mime_text"):
                self.meta_mime_text.config(text=(mime or ""))
        else:
            if hasattr(self, "meta_kind_value"):
                self.meta_kind_value.config(text=kind)
        self.meta_size.config(text=size)
        self.meta_modified.delete(0, tk.END); self.meta_modified.insert(0, mtime_str)
        self.meta_mode.delete(0, tk.END);     self.meta_mode.insert(0, mode_str)

        self._meta_original = {"filename": p.name, "modified": mtime_str, "mode": mode_str}
        self._create_mode = None
        self._set_accept_enabled(False)
        self._update_meta_safety_from_entry()

    def _on_meta_edited(self, _evt):
        self._update_meta_safety_from_entry()

        if self._create_mode:
            modified_ok = self._validate_datetime(self.meta_modified.get().strip())
            mode_ok     = self._validate_mode(self.meta_mode.get().strip())
            filename_nonempty = bool(self.meta_filename.get().strip())
            self._set_accept_enabled(filename_nonempty and modified_ok and mode_ok)
            return

        if not self._selected_path:
            self._set_accept_enabled(False)
            return

        dirty = (
            self.meta_filename.get() != self._meta_original["filename"] or
            self.meta_modified.get() != self._meta_original["modified"] or
            self.meta_mode.get()     != self._meta_original["mode"]
        )
        self._set_accept_enabled(dirty)

    def _set_accept_enabled(self, enabled: bool):
        if enabled: self.accept_btn.state(["!disabled"])
        else:       self.accept_btn.state(["disabled"])

    # ---------------- Accept / Cancel / Delete ----------------

    def _on_accept(self):
        if self._create_mode:
            name = self.meta_filename.get().strip()
            if not name:
                messagebox.showerror("Invalid", "Please enter a filename or folder name.")
                return
            mod_str  = self.meta_modified.get().strip()
            mode_str = self.meta_mode.get().strip()

            ok, mod_ts = self._parse_datetime(mod_str)
            if not ok:
                messagebox.showerror("Invalid Modified", "Use format: YYYY-MM-DD HH:MM:SS"); return
            ok, mode_val = self._parse_mode(mode_str)
            if not ok:
                messagebox.showerror("Invalid Mode", "Enter an octal like 0644 or 755 (0–7777)."); return

            try:
                target = Path(name)
                if not target.is_absolute():
                    target = (self.cwd / target).resolve()
            except Exception as e:
                messagebox.showerror("Invalid Filename", f"Cannot resolve path: {name}\n{e}"); return
            if target.exists():
                messagebox.showerror("Exists", f"Target already exists:\n{target}"); return

            try:
                if self._create_mode == "dir":
                    target.mkdir(parents=True, exist_ok=False)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, "x"): pass
                st = target.stat()
                os.utime(target, (st.st_atime, mod_ts))
                os.chmod(target, mode_val)
            except Exception as e:
                messagebox.showerror("Create Failed", f"Could not create:\n{e}"); return

            self.refresh_file_panel()
            self._selected_path = target
            self._select_path(target)
            self._load_metadata_from_path(target)
            self._create_mode = None
            self._set_accept_enabled(False)
            return

        if not self._selected_path:
            return

        src = self._selected_path
        was_cwd = (src == self.cwd)
        new_name = self.meta_filename.get().strip()
        if new_name == "":
            messagebox.showerror("Invalid", "Filename cannot be empty.")
            return
        new_mtime_str = self.meta_modified.get().strip()
        new_mode_str  = self.meta_mode.get().strip()

        ok, new_mtime_ts = self._parse_datetime(new_mtime_str)
        if not ok:
            messagebox.showerror("Invalid Modified", "Use format: YYYY-MM-DD HH:MM:SS"); return
        ok, mode_val = self._parse_mode(new_mode_str)
        if not ok:
            messagebox.showerror("Invalid Mode", "Enter an octal like 0644 or 755 (0–7777)."); return

        try:
            target = Path(new_name)
            if not target.is_absolute():
                target = (src.parent / target).resolve()
        except Exception as e:
            messagebox.showerror("Invalid Filename", f"Cannot resolve path: {new_name}\n{e}"); return

        do_rename = (target != src)
        if do_rename and target.exists():
            messagebox.showerror("Exists", f"Target already exists:\n{target}"); return

        try:
            if do_rename:
                src.rename(target)
                src = target
                self._selected_path = target
                if was_cwd and target.is_dir():
                    self.set_cwd(target)

            st = src.stat()
            os.utime(src, (st.st_atime, new_mtime_ts))
            os.chmod(src, mode_val)
        except Exception as e:
            messagebox.showerror("Apply Failed", f"Could not apply changes:\n{e}"); return

        if not was_cwd:
            self.refresh_file_panel()
        self._selected_path = src
        self._select_path(src)
        self._load_metadata_from_path(src)
        self._set_accept_enabled(False)

    def _on_cancel(self):
        if self._create_mode:
            self._create_mode = None
            self.refresh_file_panel()
            return

        if not self._selected_path:
            self._set_accept_enabled(False)
            return

        self._load_metadata_from_path(self._selected_path)
        self._set_accept_enabled(False)

    def _on_delete(self):
        if self._create_mode:
            return
        p = self._selected_path
        if not p:
            messagebox.showinfo("Delete", "No item selected.")
            return
        if not hasattr(self, "delete_path"):
            messagebox.showerror("Delete Unavailable",
                                 "Delete operation is not configured by the application.")
            return
        label = f"folder:\n{p}" if p.is_dir() else f"file:\n{p}"
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete this {label}?",
                                   icon="warning", default="no"):
            return
        try:
            self.delete_path(p)  # main.py must implement this
        except Exception as e:
            messagebox.showerror("Delete Failed", f"Could not delete:\n{e}")
            return
        if p == self.cwd:
            self.set_cwd(p.parent if p.parent.exists() else Path.home())
        else:
            self.refresh_file_panel()
            self._selected_path = None
            self._set_accept_enabled(False)

    # ---------------- Safety dialog (metadata face only) ----------------

    def _on_meta_flag_clicked(self):
        current = self.meta_filename.get()
        issues = self._filename_issues(current)
        if not issues:
            return
        self._show_safety_dialog_and_maybe_sanitize(current)

    def _show_safety_dialog_and_maybe_sanitize(self, name: str):
        issues = self._filename_issues(name)
        if not issues:
            return
        msg = "The current filename has potential issues:\n\n- " + "\n- ".join(issues) + \
              "\n\nSanitize now? (You can still review and Accept later.)"
        if messagebox.askyesno("Filename Safety", msg, icon="warning", default="yes"):
            new_name = name
            dls = deceptive_line_sanitize(new_name, low_aggression=False)
            if dls is not None:
                new_name = dls
            bfs = bad_filename_sanitize(new_name)
            if bfs is not None:
                new_name = bfs

            if new_name != name:
                self.meta_filename.delete(0, tk.END)
                self.meta_filename.insert(0, new_name)
                self._on_meta_edited(None)
            else:
                messagebox.showinfo("Sanitize", "No changes were necessary after sanitation.")

    def _update_meta_safety_from_entry(self):
        name = self.meta_filename.get()
        icon = self._meta_safety_icon(name)
        is_safe = (icon == "🙂")
        self.meta_fname_flag.config(text=icon,
                                    fg=(self._FG_TEXT if is_safe else self._ERR_RED))

    # ---------------- Misc helpers ----------------

    def _go_up(self):
        if not self.cwd:
            return
        parent = self.cwd.parent
        if parent and parent != self.cwd and parent.exists():
            self.set_cwd(parent)

    def _update_nav_buttons(self):
        try:
            parent = self.cwd.parent if self.cwd else None
            at_root = (not self.cwd) or (parent == self.cwd) or (parent is None) or (not parent.exists())
            if at_root: self.up_btn.state(["disabled"])
            else:       self.up_btn.state(["!disabled"])
        except Exception:
            self.up_btn.state(["disabled"])

    def _breadcrumb_items(self):
        p = Path(self.cwd).resolve() if getattr(self, "cwd", None) else None
        if not p:
            return []
        parts = list(p.parts)
        items = []
        if p.anchor:
            acc = Path(p.anchor); start_idx = 1
        else:
            acc = Path(parts[0]) if parts else Path("."); start_idx = 1 if parts else 0
        for name in parts[start_idx:]:
            acc = acc / name; items.append((acc, name))
        if not items and parts:
            items.append((p, parts[-1]))
        return items

    def _values_for_path(self, p: Path) -> dict:
        out = {"#0": "", "name": "", "size": "", "modified": "", "mode": ""}
        try:
            st = p.stat()
            is_dir = p.is_dir()
            out["#0"] = "Folder" if is_dir else "File"
            out["name"] = p.name
            out["size"] = "-" if is_dir else self._human_size(st.st_size)
            out["modified"] = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            out["mode"] = f"{stat.S_IMODE(st.st_mode):04o}"
        except Exception:
            out["#0"] = "Folder" if p.is_dir() else "File"
            out["name"] = p.name
        return out

    @staticmethod
    def _human_size(n: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]; i = 0; f = float(n)
        while f >= 1024 and i < len(units) - 1:
            f /= 1024.0; i += 1
        return f"{f:.1f} {units[i]}"

    @staticmethod
    def _validate_datetime(s: str) -> bool:
        try:
            time.strptime(s, "%Y-%m-%d %H:%M:%S"); return True
        except Exception:
            return False

    @staticmethod
    def _parse_datetime(s: str):
        try:
            return True, time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))
        except Exception:
            return False, None

    @staticmethod
    def _validate_mode(s: str) -> bool:
        try:
            cleaned = s.strip().lstrip("0") or "0"
            v = int(cleaned, 8); return 0 <= v <= 0o7777
        except Exception:
            return False

    @staticmethod
    def _parse_mode(s: str):
        try:
            cleaned = s.strip().lstrip("0") or "0"
            v = int(cleaned, 8)
            if not (0 <= v <= 0o7777): return False, None
            return True, v
        except Exception:
            return False, None

    # ---------------- XDG icon + MIME helpers ----------------

    def _load_ext_overrides(self) -> Dict[str, str]:
        """
        Load 'extensions.txt' from THIS module's directory only (no fallbacks).

        Format per line:
            .py text/x-python
            js = application/javascript
        - Leading '.' on the extension is optional.
        - Separator can be whitespace or '='.
        - Lines starting with '#' or blank lines are ignored.

        If the file is missing or yields no valid mappings, show an error and exit.
        """
        import sys
        from tkinter import messagebox

        here = Path(__file__).resolve().parent
        path = here / "extensions.txt"

        if not path.is_file():
            msg = (
                "Zeropad requires 'extensions.txt' next to the code:\n\n"
                f"  {path}\n\n"
                "Create the file with lines like:\n\n"
                ".py   text/x-python\n"
                ".js   application/javascript\n"
                ".yml  text/yaml\n"
                ".json application/json\n\n"
                "Then restart Zeropad."
            )
            try:
                messagebox.showerror("Missing extensions.txt", msg)
            except Exception:
                print(msg, file=sys.stderr)
            try:
                if hasattr(self, "exit_app") and callable(getattr(self, "exit_app")):
                    self.after(0, self.exit_app)
                else:
                    self.after(0, self.destroy)
            except Exception:
                pass
            raise SystemExit(1)

        # Parse the single required file
        try:
            mapping: Dict[str, str] = {}
            for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    left, right = line.split("=", 1)
                else:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    left, right = parts[0], " ".join(parts[1:])
                ext = left.strip().lower()
                mime = right.strip()
                if not ext or not mime:
                    continue
                if not ext.startswith("."):
                    ext = "." + ext
                mapping[ext] = mime

            if mapping:
                return mapping
        except Exception:
            # Fall through to error below
            pass

        # File existed but produced no usable mappings
        msg = (
            "'extensions.txt' was found but contained no valid mappings:\n\n"
            f"  {path}\n\n"
            "Each line must be '<ext> <mime>' or '<ext>=<mime>', e.g.:\n"
            ".py   text/x-python\n"
            "js = application/javascript\n"
            ".yml  text/yaml\n"
            ".json application/json\n"
        )
        try:
            messagebox.showerror("Invalid extensions.txt", msg)
        except Exception:
            print(msg, file=sys.stderr)
        try:
            if hasattr(self, "exit_app") and callable(getattr(self, "exit_app")):
                self.after(0, self.exit_app)
            else:
                self.after(0, self.destroy)
        except Exception:
            pass
        raise SystemExit(1)
        

    def _guess_mime_for(self, path: Path) -> Tuple[Optional[str], Optional[str]]:
        # Cache lookup
        try:
            if path in self._mime_cache:
                return self._mime_cache[path]
        except TypeError:
            pass

        # Directories are well-known
        try:
            if path.is_dir():
                result = ("inode/directory", "inode-directory")
                self._mime_cache[path] = result
                return result
        except Exception:
            pass

        # MIME disabled → return nothing (icon/kind handled elsewhere)
        if not self._mime_enabled():
            result = (None, None)
            self._mime_cache[path] = result
            return result

        mime: Optional[str] = None
        icon_name: Optional[str] = None

        try:
            # 1) Extension override has PRIORITY (fixes empty .py → text/x-python)
            ext = path.suffix.lower()
            if ext and ext in self._ext_overrides:
                mime = self._ext_overrides[ext]

            # 2) If no override, ask Gio (with sniffed bytes)
            if mime is None:
                data = None
                try:
                    with open(path, "rb") as f:
                        data = f.read(8192)
                except Exception:
                    data = None

                ctype, _uncertain = Gio.content_type_guess(str(path), data)
                if ctype:
                    mime = Gio.content_type_get_mime_type(ctype) or ctype

            # 3) If Gio fell back to zerosize/plain and we DO have an override, prefer override
            if ext and ext in self._ext_overrides:
                if mime in (None, "", "application/x-zerosize", "text/plain", "application/octet-stream"):
                    mime = self._ext_overrides[ext]

            # 4) Resolve themed icon name
            if mime:
                icon = Gio.content_type_get_icon(Gio.content_type_from_mime_type(mime) or mime)
            else:
                icon = None

            if icon:
                if isinstance(icon, Gio.ThemedIcon):
                    names = icon.get_names()
                    for nm in names:
                        if self._resolve_icon_path(nm):
                            icon_name = nm; break
                    if icon_name is None and names:
                        icon_name = names[0]
                else:
                    s = icon.to_string()
                    if s:
                        for nm in s.split(","):
                            nm = nm.strip()
                            if self._resolve_icon_path(nm):
                                icon_name = nm; break
                        if icon_name is None:
                            icon_name = s.split(",")[0].strip()

            if icon_name is None:
                if mime and mime.startswith("text/"):
                    icon_name = "text-x-generic"
                else:
                    icon_name = "application-octet-stream"

            result = (mime, icon_name)
            self._mime_cache[path] = result
            return result
        except Exception:
            result = (None, None)
            self._mime_cache[path] = result
            return result

    def _pixbuf_to_photoimage(self, pb: "GdkPixbuf.Pixbuf") -> Optional[tk.PhotoImage]:
        if not _HAS_GDKPB or pb is None:
            return None
        try:
            ok, buf = pb.save_to_bufferv("png", [], [])
            if not ok:
                return None
            return tk.PhotoImage(data=buf, format="png")
        except Exception:
            return None

    def _resolve_icon_path(self, icon_name: str) -> Optional[Path]:
        if not icon_name:
            return None
        names = {icon_name}
        if icon_name.endswith(".png") or icon_name.endswith(".svg"):
            names.add(icon_name.rsplit(".", 1)[0])
        else:
            names.add(icon_name + ".png")
            names.add(icon_name + ".svg")

        roots = [
            Path.home() / ".icons",
            Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "icons",
            Path("/usr/local/share/icons"),
            Path("/usr/share/icons"),
            Path("/usr/share/pixmaps"),
        ]

        theme_dirs = []
        for r in roots:
            if Path(r).exists():
                try:
                    for d in Path(r).iterdir():
                        if d.is_dir():
                            theme_dirs.append(d)
                except Exception:
                    pass
        theme_dirs += [Path("/usr/share/icons/hicolor"), Path("/usr/share/icons/Adwaita")]

        sizes = ["16x16", "22x22", "24x24", "32x32"]
        cats  = ["mimetypes", "places", "apps", "status"]

        for tdir in theme_dirs:
            for sz in sizes:
                for cat in cats:
                    d = tdir / sz / cat
                    if not d.exists():
                        continue
                    for nm in list(names):
                        p = d / nm
                        if p.is_file():
                            return p

        for tdir in theme_dirs:
            d = tdir / "scalable"
            if not d.exists():
                continue
            for cat in cats:
                cdir = d / cat
                if not cdir.exists():
                    continue
                for nm in list(names):
                    p = cdir / (nm if nm.endswith(".svg") else nm + ".svg")
                    if p.is_file():
                        return p

        for r in roots:
            if Path(r).exists():
                for nm in list(names):
                    p = Path(r) / nm
                    if p.is_file():
                        return p
        return None

    def _load_icon_image(self, icon_name: str, size: int = 16) -> Optional[tk.PhotoImage]:
        if not icon_name:
            return None
        key = f"{icon_name}@{size}"
        img = self._img_cache.get(key)
        if img:
            return img

        path = self._resolve_icon_path(icon_name)
        if path is None:
            return None

        try:
            suffix = path.suffix.lower()
            if suffix == ".png":
                img = tk.PhotoImage(file=str(path))
            elif suffix == ".svg" and _HAS_GDKPB:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), size, size)
                img = self._pixbuf_to_photoimage(pb)
            else:
                img = None
            if img:
                self._img_cache[key] = img
                return img
        except Exception:
            return None
        return None
