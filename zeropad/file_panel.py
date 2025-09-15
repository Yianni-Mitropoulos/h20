"""
FILE PANEL (Zeropad)

COLUMN WIDTH MODEL — READ THIS BEFORE EDITING:

We use a FIXED-WIDTH model for non-filename columns, with ONE flex column
(the filename) that absorbs remaining space. Users can drag separators to
resize fixed columns; those pixel widths are persisted in `_col_target_px`.

Layout on each refresh:
  1) For every *visible* non-filename column, clamp the persisted target px
     to [min..max] and sum them.
  2) Filename column width = remaining pixels, clamped to its own min (no max).
     This guarantees the tree fills the full width without snapping weirdly.

Max widths keep icon/safety columns narrow enough to avoid “ugly stretching”.

PERIODIC REFRESH:

We compute a signature of the current directory (names + size + mtime) and only
repaint the tree when it changes, preserving the current selection and all
column sizes. The refresh interval is configurable via FS_REFRESH_MS.

SAFETY FACES:

The “safety” column has an empty heading (no '!') and shows either an empty cell
(safe/OK) or a ☹ when the filename fails the aggressive deceptive or filename check.
You can sort by this column; triangles show like any other heading.

MODE STRINGS:

Mode is displayed and edited as symbolic `drwxr-xr-x` (no octal). We parse and
apply this back to the filesystem. The leading `d` (for directories) is accepted
but ignored on write; we write only the permission bits.
"""

import os
import stat
import time
import re
import subprocess
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
    # ---------- constants you may want to tweak ----------
    FS_REFRESH_MS = 2000  # periodic filesystem refresh (ms)

    # Default desired pixel widths (for fixed columns). Filename flexes.
    _COL_TARGET_PX_DEFAULT: Dict[str, int] = {
        "#0":       120,   # icon/kind or filename (when Type OFF)
        "name":     260,   # filename (flex)
        "safe":      28,   # safety faces (empty or ☹)
        "size":     110,
        "modified": 180,
        "mode":     140,   # wider now for rwx symbolic
    }
    # Minimum widths
    _COL_MIN_PX: Dict[str, int] = {
        "#0": 56, "name": 140, "safe": 24, "size": 80, "modified": 140, "mode": 110
    }
    # Base maximum widths (dynamic caps may override at runtime)
    _COL_MAX_PX_BASE: Dict[str, int] = {
        "#0": 240, "name": 10_000, "safe": 28, "size": 220, "modified": 320, "mode": 220
    }
    # Base column alignments (dynamic for "#0" depending on icon vs text)
    _COL_ANCHOR_BASE: Dict[str, str] = {
        "#0": "w", "name": "w", "safe": "center", "size": "w", "modified": "w", "mode": "w"
    }

    # -----------------------------------------------------

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

        # Load ext overrides from extensions.txt (required)
        self._ext_overrides = self._load_ext_overrides()

        # Root frame
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

        # --- Width model storage ---
        self._col_target_px: Dict[str, int] = dict(self._COL_TARGET_PX_DEFAULT)
        self._col_min_px: Dict[str, int] = dict(self._COL_MIN_PX)
        self._col_max_px_base: Dict[str, int] = dict(self._COL_MAX_PX_BASE)
        self._col_anchor_base: Dict[str, str] = dict(self._COL_ANCHOR_BASE)

        # Resizing
        self._resizing_col = False
        self._resized_col: Optional[str] = None
        self.tree.bind("<ButtonPress-1>", self._on_tree_press, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release, add="+")
        self.tree.bind("<Configure>", lambda _e: self._apply_fixed_widths())

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # Node map and state
        self._node: Dict[str, Dict] = {}
        self._sort_key = "#0"   # start on Type
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

        # Row 0: Type (unified) — icon + MIME (or plain kind)
        self._row0_left  = tk.Frame(form, bg=self._BG_PANEL)
        self._row0_value = tk.Frame(form, bg=self._BG_PANEL)
        self._row0_left.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._row0_value.grid(row=0, column=1, sticky="ew", pady=2)
        self._update_row0_mode_ui()

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

        # Row 4: Mode (symbolic rwx)
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

        # Selection & state
        self._selected_path: Path | None = None
        self._meta_original = {"filename": "", "modified": "", "mode": ""}
        self._create_mode: str | None = None  # None | "dir" | "file"

        for w in (self.meta_filename, self.meta_modified, self.meta_mode):
            w.bind("<KeyRelease>", self._on_meta_edited)

        # Image cache
        self._img_cache: dict[str, tk.PhotoImage] = {}

        # Directory signature for periodic refresh
        self._dir_sig = None
        self._fs_after_id = None

        # Build columns & first paint
        self._apply_tree_columns()

        # Start periodic refresh & register cleanup
        self._schedule_fs_refresh()
        if not hasattr(self, "_cleanup_hooks"):
            self._cleanup_hooks = []
        self._cleanup_hooks.append(self._cancel_fs_refresh)

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
            cols += ["name", "safe"]; heads["name"] = "Filename"; heads["safe"] = ""
        else:
            cols += ["safe"];         heads["safe"] = ""
        if self.col_size.get():     cols.append("size");     heads["size"] = "Size"
        if self.col_modified.get(): cols.append("modified"); heads["modified"] = "Modified"
        if self.col_mode.get():     cols.append("mode");     heads["mode"] = "Mode"
        return cols, heads

    def _apply_tree_columns(self):
        cols, heads = self._tree_columns()
        self.tree.configure(columns=cols)

        # #0 heading: empty label when showing icons; triangles still appear
        self.tree.heading("#0", text=self._sort_label_for("#0"), anchor="center",
                          command=lambda: self._on_heading_click("#0"))
        for c in ("name", "safe", "size", "modified", "mode"):
            if c not in cols:
                continue
            if c == "safe":
                self.tree.heading(c, text=self._sort_label_for("safe"),
                                  anchor="center", command=lambda col="safe": self._on_heading_click(col))
                continue
            self.tree.heading(c, text=self._sort_label_for(c), command=lambda col=c: self._on_heading_click(col))

        self._apply_fixed_widths()
        self.refresh_file_panel()

    def _filename_flex_col(self) -> str:
        return "name" if self.col_type.get() else "#0"

    def _dynamic_max_caps(self) -> Dict[str, int]:
        caps = dict(self._col_max_px_base)
        if self.col_type.get() and self._mime_enabled():
            caps["#0"] = 40  # icon column stays tiny
        else:
            if not self.col_type.get():
                caps["#0"] = 10_000  # when #0 is filename, allow growth
        caps[self._filename_flex_col()] = 10_000_000  # filename flex column
        # Safety column should never bloat
        caps["safe"] = min(caps.get("safe", 28), 28)
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
                anchor = "center" if (self.col_type.get() and self._mime_enabled()) else self._col_anchor_base.get("#0", "w")
            else:
                anchor = self._col_anchor_base.get(c, "w")
            self.tree.column(c, width=max(1, col_widths[c]), stretch=True, anchor=anchor)

        # Park hidden data columns
        for c in ("name", "safe", "size", "modified", "mode"):
            if c not in self.tree["columns"]:
                continue
            if c not in vis:
                self.tree.column(c, width=self._col_min_px.get(c, 50), stretch=False,
                                 anchor=self._col_anchor_base.get(c, "w"))

    # capture user resize to update fixed target widths
    def _on_tree_press(self, event):
        self._resizing_col = (self.tree.identify_region(event.x, event.y) == "separator")
        self._resized_col = None
        if self._resizing_col:
            col_id = self.tree.identify_column(event.x)  # '#0', '#1', ...
            if col_id == "#0":
                self._resized_col = "#0"
            else:
                try:
                    idx = int(col_id.replace("#", "")) - 1
                    cols = list(self.tree["columns"])
                    if 0 <= idx < len(cols):
                        self._resized_col = cols[idx]
                except Exception:
                    self._resized_col = None

    def _on_tree_release(self, _event):
        if self._resizing_col:
            vis = self._visible_cols()
            # Allow resizing any visible fixed column; resizing the flex column does nothing meaningful
            if self._resized_col in vis and self._resized_col != self._filename_flex_col():
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
        self.refresh_file_panel(force=True)

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
            if col == "safe":
                base = ""  # header is visually empty; triangles still show
            else:
                base = "Filename" if col == "name" else col.capitalize()
        if col == self._sort_key:
            return f"{base} {'▼' if not self._sort_desc else '▲'}".strip()
        return base

    def _key_for_entry(self, p: Path, key: str):
        """
        Stable, minimal keys (no fallback to name unless key=='name').
        Directories are grouped before files (0/1).
        """
        is_dir = 0 if p.is_dir() else 1
        try:
            if key == "name":
                return (is_dir, p.name.lower())
            if key == "kind":
                return (is_dir, 0)  # folders vs files; ties stable
            if key == "mime":
                if p.is_dir():
                    return (0, 0)
                mime, _ = self._guess_mime_for(p)
                return (1, (mime or "application/octet-stream").lower())
            if key == "safe":
                unsafe = 0 if not self._is_name_safe(p.name) else 1  # unsafe first
                return (is_dir, unsafe)
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
        self.refresh_file_panel(force=True)

    # ---------------- Periodic refresh ----------------

    def _dir_signature(self) -> Tuple:
        """Return a cheap signature of the visible dir contents for change detection."""
        try:
            entries = list(self.cwd.iterdir())
        except Exception:
            entries = []
        show_hidden = self.show_hidden.get()
        def filt(e: Path):
            try:
                nm = e.name
                if not show_hidden and nm.startswith("."):
                    return False
                return e.exists()
            except Exception:
                return False
        items = []
        for e in entries:
            if not filt(e):
                continue
            try:
                st = e.stat()
                items.append((e.is_dir(), e.name, st.st_size if e.is_file() else -1, int(st.st_mtime)))
            except Exception:
                items.append((e.is_dir(), e.name, -1, 0))
        items.sort()
        return tuple(items)

    def _schedule_fs_refresh(self):
        self._fs_after_id = self.after(self.FS_REFRESH_MS, self._fs_refresh_tick)

    def _cancel_fs_refresh(self):
        if getattr(self, "_fs_after_id", None):
            try:
                self.after_cancel(self._fs_after_id)
            except Exception:
                pass
            self._fs_after_id = None

    def _fs_refresh_tick(self):
        try:
            sig = self._dir_signature()
            if sig != self._dir_sig:
                self._dir_sig = sig
                self.refresh_file_panel(force=True)
        finally:
            self._schedule_fs_refresh()

    # ---------------- Rendering ----------------

    def refresh_file_panel(self, force: bool = False):
        # ensure headings reflect current (also shows triangles)
        cols, heads = self._tree_columns()
        self.tree.configure(columns=cols)

        self.tree.heading("#0", text=self._sort_label_for("#0"), anchor="center",
                          command=lambda: self._on_heading_click("#0"))
        for c in ("name", "safe", "size", "modified", "mode"):
            if c in cols:
                self.tree.heading(c, text=self._sort_label_for(c),
                                  command=lambda col=c: self._on_heading_click(col),
                                  anchor=("center" if c in ("safe",) else "w"))

        self._apply_fixed_widths()

        cwd_changed = (self._last_cwd is None) or (self.cwd != self._last_cwd) or force
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

        # Breadcrumbs (unsorted)
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

        # Create New Folder (bold)
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

        # Create New File (bold)
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

    # ---------------- Selection & double-click ----------------

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
        mode = "rwxr-xr-x" if what == "dir" else "rw-r--r--"
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

    def get_selected_path(self) -> Optional[Path]:
        """Return the currently selected filesystem Path (or None)."""
        # Prefer our tracked selection
        if getattr(self, "_selected_path", None):
            return self._selected_path
        # Fallback: read from the tree selection if present
        try:
            sels = self.tree.selection()
            if not sels:
                return None
            meta = self._node.get(sels[0], {})
            p = meta.get("path")
            return Path(p) if p else None
        except Exception:
            return None


    def _on_tree_double_click(self, event):
        """React only to double-clicks on actual rows.
        - Files (role='cwd-file')  → select it, then delegate to File→Open Selected.
        - Directories (breadcrumbs/cwd-dir) → cd into
        - 'Create New …' rows → enter create mode
        - Headings/separators/empty space → ignore
        """
        region = self.tree.identify_region(event.x, event.y)
        if region not in ("tree", "cell"):  # ignore heading, separator, nothing
            return

        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return

        info = self._node.get(row_id, {})
        kind = info.get("kind")
        role = info.get("role")
        path = info.get("path")

        # Only show the open dialog for files that live in the cwd list
        if kind == "file" and role == "cwd-file" and path:
            # Make sure the UI selection matches the clicked row before delegating
            try:
                self.tree.selection_set(row_id)
                self.tree.focus(row_id)
            except Exception:
                pass
            # Track selection for menus._menu_open_selected()
            self._selected_path = Path(path)
            self._create_mode = None
            # Delegate to the same logic used by File → Open Selected
            if hasattr(self, "_menu_open_selected") and callable(getattr(self, "_menu_open_selected")):
                self._menu_open_selected()
            else:
                # Fallback: open chooser directly (shouldn't normally happen)
                self._prompt_open_file(Path(path))
            return

        # Navigate on directories (breadcrumbs or cwd)
        if kind == "dir" and path and role in ("breadcrumb", "cwd-dir"):
            self.set_cwd(path)
            return

        # “Create new …” rows
        if kind == "create_file":
            self._enter_create_mode("file")
            return
        if kind == "create_dir":
            self._enter_create_mode("dir")
            return

        # Anything else: no-op

    def _prompt_open_file(self, path: Path):
        """Three-way chooser: Cancel, System Default (xdg-open), Zeropad editor."""
        win = tk.Toplevel(self)
        win.withdraw()  # build off-screen to avoid flicker
        win.title("Open File")
        win.configure(bg=self._BG_PANEL)
        win.transient(self)  # keep above parent

        # Content
        tk.Label(
            win,
            text=f"Open:\n{path}",
            bg=self._BG_PANEL,
            fg=self._FG_TEXT,
            justify="left"
        ).pack(side="top", anchor="w", padx=12, pady=12)

        btns = tk.Frame(win, bg=self._BG_PANEL)
        btns.pack(side="top", fill="x", padx=12, pady=12)

        def do_cancel():
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

        def do_system():
            try:
                subprocess.Popen(
                    ["xdg-open", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                messagebox.showerror("Open Failed", f"xdg-open error:\n{e}")
            do_cancel()

        def do_zeropad():
            # Close dialog first (releases grab), then open the file in the next idle tick.
            do_cancel()
            # TextPanel provides open_with_zeropad(Path)
            if hasattr(self, "open_with_zeropad"):
                self.after_idle(lambda: self.open_with_zeropad(Path(path)))
            else:
                messagebox.showerror("Unavailable", "Open in Zeropad is not wired up in TextPanel.")

        ttk.Button(btns, text="Cancel", style="Secondary.TButton", command=do_cancel).pack(side="right")
        ttk.Button(btns, text="Open in Zeropad", style="Primary.TButton", command=do_zeropad)\
            .pack(side="right", padx=(0, 8))
        ttk.Button(btns, text="Open with System Default", style="Secondary.TButton", command=do_system)\
            .pack(side="right", padx=(0, 8))

        win.bind("<Escape>", lambda e: do_cancel())
        win.protocol("WM_DELETE_WINDOW", do_cancel)

        # Layout/center, then map & raise
        win.update_idletasks()
        try:
            px, py = self.winfo_rootx(), self.winfo_rooty()
            pw, ph = self.winfo_width(), self.winfo_height()
            ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
            x = px + max(0, (pw - ww) // 2)
            y = py + max(0, (ph - wh) // 3)
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass

        win.deiconify()
        win.lift()

        # Take grab only after the window is viewable
        def _try_grab():
            if win.winfo_viewable():
                try:
                    win.grab_set()
                except Exception:
                    win.after(10, _try_grab)
            else:
                win.after(10, _try_grab)

        _try_grab()
        win.focus_set()
        win.wait_window()

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
        mode_sym = self._mode_to_symbolic(st.st_mode, p.is_dir())

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
        self.meta_mode.delete(0, tk.END);     self.meta_mode.insert(0, mode_sym)

        self._meta_original = {"filename": p.name, "modified": mtime_str, "mode": mode_sym}
        self._create_mode = None
        self._set_accept_enabled(False)
        self._update_meta_safety_from_entry()

    def _on_meta_edited(self, _evt):
        self._update_meta_safety_from_entry()

        if self._create_mode:
            modified_ok = self._validate_datetime(self.meta_modified.get().rstrip())
            mode_ok     = self._validate_mode_symbolic(self.meta_mode.get().rstrip())
            filename_nonempty = bool(self.meta_filename.get().rstrip())
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
        # CREATE mode
        if self._create_mode:
            name = self.meta_filename.get().rstrip()  # ONLY strip trailing spaces
            if not name:
                messagebox.showerror("Invalid", "Please enter a filename or folder name.")
                return
            mod_str  = self.meta_modified.get().rstrip()
            mode_sym = self.meta_mode.get().rstrip()

            ok, mod_ts = self._parse_datetime(mod_str)
            if not ok:
                messagebox.showerror("Invalid Modified", "Use format: YYYY-MM-DD HH:MM:SS"); return
            ok, mode_val = self._parse_mode_symbolic(mode_sym)
            if not ok:
                messagebox.showerror("Invalid Mode", "Use symbolic like rwxr-xr-x (optional leading d)."); return

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
                    with open(target, "x"):
                        pass
                st = target.stat()
                os.utime(target, (st.st_atime, mod_ts))
                os.chmod(target, mode_val)
            except Exception as e:
                messagebox.showerror("Create Failed", f"Could not create:\n{e}"); return

            self.refresh_file_panel(force=True)
            self._selected_path = target
            self._select_path(target)
            self._load_metadata_from_path(target)
            self._create_mode = None
            self._set_accept_enabled(False)
            return

        # EDIT mode
        if not self._selected_path:
            return

        src = self._selected_path
        was_cwd = (src == self.cwd)
        new_name = self.meta_filename.get().rstrip()  # ONLY strip trailing
        if new_name == "":
            messagebox.showerror("Invalid", "Filename cannot be empty.")
            return
        new_mtime_str = self.meta_modified.get().rstrip()
        new_mode_sym  = self.meta_mode.get().rstrip()

        ok, new_mtime_ts = self._parse_datetime(new_mtime_str)
        if not ok:
            messagebox.showerror("Invalid Modified", "Use format: YYYY-MM-DD HH:MM:SS"); return
        ok, mode_val = self._parse_mode_symbolic(new_mode_sym)
        if not ok:
            messagebox.showerror("Invalid Mode", "Use symbolic like rwxr-xr-x (optional leading d)."); return

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
            old_path = src
            if do_rename:
                src.rename(target)
                src = target
                self._selected_path = target
                # Notify TextPanel so any open tab updates its path/title WITHOUT changing dirty
                if hasattr(self, "on_path_renamed") and callable(getattr(self, "on_path_renamed")):
                    try:
                        self.on_path_renamed(old_path, target)
                    except Exception:
                        pass
                if was_cwd and target.is_dir():
                    self.set_cwd(target)

            st = src.stat()
            os.utime(src, (st.st_atime, new_mtime_ts))
            os.chmod(src, mode_val)
        except Exception as e:
            messagebox.showerror("Apply Failed", f"Could not apply changes:\n{e}"); return

        if not was_cwd:
            self.refresh_file_panel(force=True)
        self._selected_path = src
        self._select_path(src)
        self._load_metadata_from_path(src)
        self._set_accept_enabled(False)

    def _on_cancel(self):
        if self._create_mode:
            self._create_mode = None
            self.refresh_file_panel(force=True)
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
            self.refresh_file_panel(force=True)
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
            out["mode"] = self._mode_to_symbolic(st.st_mode, is_dir)
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

    # ----- rwx mode helpers (symbolic) -----

    @staticmethod
    def _mode_to_symbolic(mode: int, is_dir: bool) -> str:
        # leading file type char
        t = "d" if is_dir else "-"
        perms = ""
        for who in (stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR,
                    stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP,
                    stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH):
            perms += (
                "r" if (who in (stat.S_IRUSR, stat.S_IRGRP, stat.S_IROTH) and (mode & who)) else
                "w" if (who in (stat.S_IWUSR, stat.S_IWGRP, stat.S_IWOTH) and (mode & who)) else
                "x" if (who in (stat.S_IXUSR, stat.S_IXGRP, stat.S_IXOTH) and (mode & who)) else
                "-"
            )
        # handle setuid/setgid/sticky
        if mode & stat.S_ISUID:
            perms = perms[:2] + ("s" if (mode & stat.S_IXUSR) else "S") + perms[3:]
        if mode & stat.S_ISGID:
            perms = perms[:5] + ("s" if (mode & stat.S_IXGRP) else "S") + perms[6:]
        if mode & stat.S_ISVTX:
            perms = perms[:8] + ("t" if (mode & stat.S_IXOTH) else "T") + perms[9:]
        return t + perms

    @staticmethod
    def _validate_mode_symbolic(s: str) -> bool:
        s = s.strip()
        return bool(re.fullmatch(r"[d-]?[rwxstST-]{9}", s))

    @staticmethod
    def _parse_mode_symbolic(s: str):
        s = s.strip()
        if not FilePanel._validate_mode_symbolic(s):
            return False, None
        if len(s) == 10:
            s = s[1:]
        # map chars
        bits = 0
        def setbit(cond, b):  # small helper
            nonlocal bits
            if cond: bits |= b

        # user
        setbit(s[0] in "r", stat.S_IRUSR)
        setbit(s[1] in "w", stat.S_IWUSR)
        ux = s[2]
        setbit(ux in "xst", stat.S_IXUSR)
        if ux in "sS": bits |= stat.S_ISUID

        # group
        setbit(s[3] in "r", stat.S_IRGRP)
        setbit(s[4] in "w", stat.S_IWGRP)
        gx = s[5]
        setbit(gx in "xst", stat.S_IXGRP)
        if gx in "sS": bits |= stat.S_ISGID

        # other
        setbit(s[6] in "r", stat.S_IROTH)
        setbit(s[7] in "w", stat.S_IWOTH)
        ox = s[8]
        setbit(ox in "xtT", stat.S_IXOTH)
        if ox in "tT": bits |= stat.S_ISVTX

        return True, bits

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
            pass

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
